#define ORT_API_MANUAL_INIT
// MinGW's SAL header lacks this optional ownership annotation used by ORT.
#if defined(_WIN32) && !defined(_MSC_VER)
#include <specstrings.h>
#ifndef _Frees_ptr_opt_
#define _Frees_ptr_opt_
#endif
#endif
#include <onnxruntime_cxx_api.h>
#include "reid_runtime.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <dlfcn.h>
#endif

namespace {
void error_text(char* buffer, size_t size, const char* message) noexcept {
    if (buffer && size) {
        size_t length = std::min(size - 1, std::strlen(message));
        std::memcpy(buffer, message, length);
        buffer[length] = '\0';
    }
}
#ifdef _WIN32
std::wstring wide(const std::string& value) {
    int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.c_str(), -1, nullptr, 0);
    if (!size) throw std::runtime_error("invalid UTF-8 path");
    std::wstring result(size, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.c_str(), -1, result.data(), size);
    return result;
}
#endif
std::once_flag api_once;
std::string loaded_library;
void init_api(const char* library) {
    if (!library || !*library) throw std::runtime_error("ORT library path is required");
    std::call_once(api_once, [library] {
#ifdef _WIN32
        // Keep ORT loaded for process lifetime; sessions and API tables reference it.
        auto module = LoadLibraryExW(wide(library).c_str(), nullptr,
                                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!module) throw std::runtime_error("cannot load ONNX Runtime DLL (check path/dependencies)");
        auto get_api = reinterpret_cast<const OrtApiBase* (ORT_API_CALL*)()>(
            GetProcAddress(module, "OrtGetApiBase"));
#else
        auto module = dlopen(library, RTLD_NOW | RTLD_LOCAL);
        if (!module) throw std::runtime_error(dlerror());
        auto get_api = reinterpret_cast<const OrtApiBase* (*)()>(dlsym(module, "OrtGetApiBase"));
#endif
        if (!get_api) throw std::runtime_error("ORT library does not export OrtGetApiBase");
        auto api = get_api()->GetApi(ORT_API_VERSION);
        if (!api) throw std::runtime_error("ORT runtime is older than the build headers");
        Ort::InitApi(api);
        loaded_library = library;
    });
    if (loaded_library != library) throw std::runtime_error("cannot change ORT library within a process");
}
Ort::Env& environment() {
    static Ort::Env env(ORT_LOGGING_LEVEL_WARNING, "reid-cpp");
    return env;
}

struct Runtime {
    struct Auxiliary {
        std::string name;
        std::vector<int64_t> shape;
        ONNXTensorElementDataType type;
        size_t bytes;
    };
    Ort::Session session{nullptr};
    Ort::MemoryInfo memory{Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault)};
    std::string input_name, output_name;
    int width = 0, height = 0, dim = 0;
    bool dynamic_batch = false;
    bool vehicle = false, flat_output = false;
    std::vector<Auxiliary> auxiliary;

    Runtime(const char* model, int threads, bool vehicle_policy = false) : vehicle(vehicle_policy) {
        if (!model || !*model || threads < 1 || threads > 64)
            throw std::runtime_error("model required; threads must be in [1,64]");
        Ort::SessionOptions options;
        options.SetIntraOpNumThreads(threads);
        options.SetInterOpNumThreads(1);
        options.SetExecutionMode(ExecutionMode::ORT_SEQUENTIAL);
        options.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
        options.AddConfigEntry("session.intra_op.allow_spinning", "0");
#ifdef _WIN32
        session = Ort::Session(environment(), wide(model).c_str(), options);
#else
        session = Ort::Session(environment(), model, options);
#endif
        if (session.GetInputCount() < 1 || (!vehicle && session.GetInputCount() != 1) || session.GetOutputCount() < 1)
            throw std::runtime_error("ReID requires exactly one input and at least one output");
        auto input_type = session.GetInputTypeInfo(0);
        auto input = input_type.GetTensorTypeAndShapeInfo();
        auto shape = input.GetShape();
        if (vehicle && shape.size() == 4) {
            // Match the existing vehicle dynamic spatial-size default.
            if (shape[2] < 0) shape[2] = 256;
            if (shape[3] < 0) shape[3] = 256;
        }
        if (input.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
            shape.size() != 4 || shape[1] != 3 || shape[2] < 1 || shape[3] < 1 ||
            shape[2] > 4096 || shape[3] > 4096 || shape[0] > 1 || shape[0] == 0)
            throw std::runtime_error("requires float32 NCHW RGB, fixed H/W <=4096, batch 1 or dynamic");
        height = static_cast<int>(shape[2]); width = static_cast<int>(shape[3]);
        dynamic_batch = shape[0] < 0;
        auto output_type = session.GetOutputTypeInfo(0);
        auto output = output_type.GetTensorTypeAndShapeInfo();
        auto out_shape = output.GetShape();
        flat_output = vehicle && out_shape.size() == 1;
        if (output.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
            (!flat_output && (out_shape.size() < 2 || (out_shape[0] > 0 && out_shape[0] != 1))) ||
            (vehicle && out_shape.size() > 2))
            throw std::runtime_error("requires float32 output with a leading batch dimension");
        size_t dimension = 1;
        for (size_t i = flat_output ? 0 : 1; i < out_shape.size(); ++i) {
            if (out_shape[i] < 1 || out_shape[i] > 65536 || dimension > 65536 / out_shape[i])
                throw std::runtime_error("requires static embedding dimension <=65536");
            dimension *= out_shape[i];
        }
        dim = static_cast<int>(dimension);
        Ort::AllocatorWithDefaultOptions allocator;
        input_name = session.GetInputNameAllocated(0, allocator).get();
        output_name = session.GetOutputNameAllocated(0, allocator).get();
        if (session.GetInputCount() > 17) throw std::runtime_error("too many vehicle auxiliary inputs");
        for (size_t i = 1; i < session.GetInputCount(); ++i) {
            auto type_info = session.GetInputTypeInfo(i);
            auto tensor = type_info.GetTensorTypeAndShapeInfo();
            auto type = tensor.GetElementType();
            size_t item_size = 0;
            switch (type) {
                case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: item_size = sizeof(float); break;
                case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: item_size = sizeof(double); break;
                case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: item_size = sizeof(int64_t); break;
                case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: item_size = sizeof(int32_t); break;
                case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: item_size = sizeof(bool); break;
                default: throw std::runtime_error("unsupported vehicle auxiliary input dtype");
            }
            auto aux_shape = tensor.GetShape();
            if (aux_shape.size() > 8) throw std::runtime_error("vehicle auxiliary input rank exceeds 8");
            size_t elements = 1;
            for (auto& d : aux_shape) {
                if (d < 0) d = 1; // Same zero-feed shape convention as the legacy extractor.
                if (d > 1048576 || (d && elements > 1048576 / d))
                    throw std::runtime_error("vehicle auxiliary tensor exceeds size limit");
                elements *= static_cast<size_t>(d);
            }
            auxiliary.push_back({session.GetInputNameAllocated(i, allocator).get(), aux_shape, type, elements * item_size});
        }
        // Auxiliary labels retain legacy single-image semantics. Do not infer
        // that arbitrary dynamic label dimensions are the image batch axis.
        if (!auxiliary.empty() || flat_output) dynamic_batch = false;
    }

    void run(const uint8_t* bgr, int count, float* result) {
        const size_t pixels = static_cast<size_t>(height) * width;
        // Per-call storage: no shared mutable input/output buffers or forward lock.
        std::vector<float> blob(static_cast<size_t>(count) * pixels * 3);
        constexpr float mean[] = {.485f, .456f, .406f};
        constexpr float stddev[] = {.229f, .224f, .225f};
        for (int n = 0; n < count; ++n)
            for (size_t p = 0; p < pixels; ++p)
                for (size_t c = 0; c < 3; ++c)
                    blob[(static_cast<size_t>(n) * 3 + c) * pixels + p] =
                        (static_cast<float>(bgr[(static_cast<size_t>(n) * pixels + p) * 3 + 2 - c]) /
                         255.0f - mean[c]) / stddev[c];
        int run_count = dynamic_batch ? count : 1;
        std::array<int64_t, 4> shape{run_count, 3, height, width};
        std::vector<const char*> inputs{input_name.c_str()};
        for (const auto& aux : auxiliary) inputs.push_back(aux.name.c_str());
        const char* outputs[] = {output_name.c_str()};
        Ort::AllocatorWithDefaultOptions allocator;
        for (int start = 0; start < count; start += run_count) {
            std::vector<Ort::Value> tensors;
            tensors.reserve(inputs.size());
            tensors.push_back(Ort::Value::CreateTensor<float>(memory, blob.data() + start * pixels * 3,
                static_cast<size_t>(run_count) * pixels * 3, shape.data(), shape.size()));
            for (const auto& aux : auxiliary) {
                auto tensor = Ort::Value::CreateTensor(allocator, aux.shape.data(), aux.shape.size(), aux.type);
                if (aux.bytes) std::memset(tensor.GetTensorMutableRawData(), 0, aux.bytes);
                tensors.push_back(std::move(tensor));
            }
            auto values = session.Run(Ort::RunOptions{nullptr}, inputs.data(), tensors.data(), inputs.size(), outputs, 1);
            auto info = values[0].GetTensorTypeAndShapeInfo();
            auto output_shape = info.GetShape();
            if (info.GetElementType() != ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ||
                output_shape.empty() || (!flat_output && output_shape[0] != run_count) ||
                info.GetElementCount() != static_cast<size_t>(run_count) * dim)
                throw std::runtime_error("output shape/type differs from declared embedding");
            const float* data = values[0].GetTensorData<float>();
            size_t size = static_cast<size_t>(run_count) * dim;
            if (!std::all_of(data, data + size, [](float x) {return std::isfinite(x);}))
                throw std::runtime_error("non-finite embedding output");
            if (vehicle) {
                for (int n = 0; n < run_count; ++n) {
                    double norm_squared = 0;
                    for (int d = 0; d < dim; ++d) {
                        double x = data[static_cast<size_t>(n) * dim + d];
                        norm_squared += x * x;
                    }
                    if (norm_squared < 1e-24) throw std::runtime_error("zero vehicle embedding output");
                }
            }
            std::copy(data, data + size, result + static_cast<size_t>(start) * dim);
        }
    }
};
}

int reid_abi_version() { return 2; }
void* reid_create(const char* library, const char* model, int threads, char* error, size_t size) {
    try { init_api(library); return new Runtime(model, threads); }
    catch (const std::exception& e) { error_text(error, size, e.what()); }
    catch (...) { error_text(error, size, "unknown native initialization error"); }
    return nullptr;
}
void* reid_create_vehicle(const char* library, const char* model, int threads, char* error, size_t size) {
    try { init_api(library); return new Runtime(model, threads, true); }
    catch (const std::exception& e) { error_text(error, size, e.what()); }
    catch (...) { error_text(error, size, "unknown native vehicle initialization error"); }
    return nullptr;
}
int reid_shape(void* handle, int* width, int* height, int* dim, int* dynamic, char* error, size_t size) {
    if (!handle || !width || !height || !dim || !dynamic) {
        error_text(error, size, "invalid shape argument"); return -1;
    }
    auto& r = *static_cast<Runtime*>(handle);
    *width = r.width; *height = r.height; *dim = r.dim; *dynamic = r.dynamic_batch;
    return 0;
}
int reid_infer(void* handle, const uint8_t* bgr, size_t input_size, int count,
               float* output, size_t output_size, char* error, size_t size) {
    try {
        if (!handle || !bgr || !output || count < 1 || count > 64)
            throw std::runtime_error("invalid infer argument; batch must be in [1,64]");
        auto& r = *static_cast<Runtime*>(handle);
        if (input_size != static_cast<size_t>(count) * r.height * r.width * 3 ||
            output_size != static_cast<size_t>(count) * r.dim)
            throw std::runtime_error("input/output buffer size mismatch");
        r.run(bgr, count, output);
        return 0;
    } catch (const std::exception& e) { error_text(error, size, e.what()); }
      catch (...) { error_text(error, size, "unknown native inference error"); }
    return -1;
}
void reid_destroy(void* handle) { delete static_cast<Runtime*>(handle); }
