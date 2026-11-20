"""Torch>=2.11 + torchao 0.12 flex_attention shim keeps transformers.pipeline importable."""
import sys
import unittest


class HfPipelineShimTest(unittest.TestCase):
    def test_import_hf_pipeline_after_shim(self):
        from inference import _import_hf_pipeline, _shim_flex_attention_for_torchao

        _shim_flex_attention_for_torchao()
        self.assertIn("torch._inductor.kernel.flex_attention", sys.modules)
        pipeline = _import_hf_pipeline()
        self.assertTrue(callable(pipeline))


if __name__ == "__main__":
    unittest.main()
