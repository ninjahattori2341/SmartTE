# SmartTE presentation source and exports

- `SmartTE_Presentation_Source.pdf` is the original user-provided slide deck, preserved unchanged.
- `rebuild_deck.py` reads that original deck and the processed E2 campaign summary under `results/processed/` to regenerate the final PDF and PPTX.
- Run from the repository root with `python presentation/rebuild_deck.py` after installing `pymupdf`, `Pillow`, and `python-pptx`.
- `SmartTE_Presentation_Final.pdf` is the exported 15-slide deck. `SmartTE_Presentation_Final.pptx` is editable for the revised results slide and the two added literature slides; source-PDF slides are retained as full-page images because no original PPTX was supplied. The conclusion slide also has its old “Questions?” heading removed and its page number updated.

The E2 chart/table values are read from `results/processed/m5_campaign_20261011T115819Z/metrics_summary.csv`. The E4 explanation is preserved from the source deck and is consistent with the processed event audit. No slide claims the published papers are numerical baselines for this emulation.
