# SmartTE final submission manifest

Final PDFs are generated from the checked project sources. The combined PDF is made by concatenating the standalone report first and standalone presentation second, without re-rendering either document.

| Deliverable | Pages | Source / generation |
|---|---:|---|
| `SmartTE_Final_Report.pdf` | 17 | `report_latex/main.tex`, `report_latex/sections/`, `report_latex/references.bib`, report figures and evidence; compiled with Tectonic. Includes the confirmed contributions on the title page. |
| `SmartTE_Final_Presentation.pdf` | 15 | `presentation/SmartTE_Presentation_Source.pdf`, `presentation/rebuild_deck.py`, and `results/processed/m5_campaign_20261011T115819Z/metrics_summary.csv`. |
| `Centralized Traffic Engineering in Data Center Networks_Ashwin Krishna G.pdf` | 32 | Concatenation of the report PDF (pages 1–17) followed by the presentation PDF (pages 18–32). |

The original supplied presentation PDF remains preserved as `presentation/SmartTE_Presentation_Source.pdf`. `presentation/SmartTE_Presentation_Final.pptx` is the editable slide source available from the supplied PDF: the revised results slide and two literature slides use native PowerPoint elements; source-PDF slides are page images because no original PPTX was available.

## Validation recorded

- Python unit suite: 20 tests passed.
- Analysis and plotting scripts ran on the 110-row M5 raw campaign into a separate validation directory. All 264 regenerated summary rows matched the checked-in processed metrics summary exactly; the campaign has 105 `ok` rows and five expected Static E4 failures.
- Report PDF: 17 pages; presentation PDF: 15 slides; combined PDF: 32 pages in the required order.
- The report title page, all report pages, and all presentation slides were rendered for visual inspection. The bundled Windows Tectonic build completed with non-fatal Fontconfig and bibliography-rerun warnings.
- Results remain descriptive (five trials per cell); no significance test or production-network validation is claimed.
