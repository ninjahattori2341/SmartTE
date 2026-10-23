# SmartTE LaTeX report

This is a separate, single-column academic report source. Single-column layout keeps the topology and campaign plots readable. Existing Markdown drafts remain in report/.

## Structure

- main.tex includes the title page and Parts A, B, C, and contributions.
- sections/ contains the source sections.
- references.bib is based on the verified bibliography in report/references.md.
- figures/ contains verified campaign plots copied from results/processed/m5_campaign_20261011T115819Z/figures/.
- evidence/SmartTE_screenshots.pdf preserves the supplied screenshot evidence PDF.
- evidence/extracted/ contains selected genuine images rasterized from evidence PDF pages; captions identify archived versus live captures and cropped proof.

## Compile

The report was compiled and visually checked with Tectonic. With Tectonic installed, run from this directory:

~~~bash
tectonic -X compile --outdir build/final main.tex
~~~

The local Windows build used a locally available `tools/tectonic.exe` with the same options. The generated 18-page PDF is `SmartTE_report.pdf`; it includes the confirmed team contribution statement on the title page and a detailed contributions section. Tectonic emitted non-fatal Fontconfig and bibliography-rerun warnings, but produced the PDF successfully. The screenshot PDF was rendered with PyMuPDF and its seven pages were visually inspected. Figures 1 and 2 are live terminal captures; Figures 3--11 are archived; Appendix Figures A1--A2 are earlier milestone evidence.

The checked-in report figures are derived from the processed M5 campaign. Regenerating plots may update the analysis metadata and plot outputs under `results/processed/`; inspect the diff before retaining those changes.

The report prose, references, and values require student review under course originality and AI-use rules. Confidence intervals are descriptive; the report does not claim statistical significance.
