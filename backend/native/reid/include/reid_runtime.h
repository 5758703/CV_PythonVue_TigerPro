#pragma once
#include <stddef.h>
#include <stdint.h>
#if defined(_WIN32)
#define REID_API extern "C" __declspec(dllexport)
#else
#define REID_API extern "C" __attribute__((visibility("default")))
#endif

// All strings are UTF-8. Errors are returned through caller-owned buffers.
// destroy must not race with infer; distinct infer calls may run concurrently.
REID_API int reid_abi_version();
REID_API void* reid_create(const char* ort_library, const char* model, int threads,
                           char* error, size_t error_size);
// ABI 2: vehicle policy also supports zero camera/view inputs and [D] output.
REID_API void* reid_create_vehicle(const char* ort_library, const char* model, int threads,
                                  char* error, size_t error_size);
REID_API int reid_shape(void* handle, int* width, int* height, int* dim, int* dynamic_batch,
                        char* error, size_t error_size);
// BGR uint8 contiguous [count,height,width,3], pre-resized with INTER_LINEAR.
// Returns raw float32 embeddings [count,dim], preserving model semantics.
REID_API int reid_infer(void* handle, const uint8_t* bgr, size_t input_size, int count,
                        float* output, size_t output_size, char* error, size_t error_size);
REID_API void reid_destroy(void* handle);
