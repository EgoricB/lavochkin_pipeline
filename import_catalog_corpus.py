"""Compatibility launcher for the package module."""
import runpy

if __name__ == "__main__":
    runpy.run_module("lavochkin_pipeline.catalog.import_corpus", run_name="__main__", alter_sys=True)
