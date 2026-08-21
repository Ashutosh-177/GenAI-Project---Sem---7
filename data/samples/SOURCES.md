# Sample document provenance

All public, downloaded 2026-08-14 for Phase 1 ingestion testing. Not QCI's actual
data — replace with real QCI documents once available; do not use these in any
client-facing demo without disclosing they're placeholders.

| File | Source | Why it's useful |
|---|---|---|
| `qci_eoi_consultant_zed.pdf` | [qcin.org](https://qcin.org/wp-content/uploads/2026/02/EoI-Consultant-Organisations_ZED.pdf) | Real QCI procurement document — closest thing to actual client data, native digital PDF |
| `mha_sample_mou.pdf` | [mha.gov.in](https://www.mha.gov.in/sites/default/files/MOUNERS_210815.pdf) | Real Govt of India MoU — tests the MoU template/drafting pattern against real structure |
| `crpf_tender.pdf` | [crpf.gov.in](https://crpf.gov.in/Upload/Tender/814092024-593.pdf) | Government tender/work-order-style document |
| `sameer_tender.pdf` | [sameer.gov.in](https://sameer.gov.in/storage/tenders/CdZokeSyJFGMrf8XPzVaYVWP8lhU82FDahz0ieGk.pdf) | Another tender doc — variety in layout/formatting |
| `dopt_scanned_circular_2001.pdf` | [documents.doptcirculars.nic.in](https://documents.doptcirculars.nic.in/D2/D02est/15012_7_91-Estt.D-20122001.pdf) | Older circular, likely scan-quality — good OCR accuracy stress test |

Not found / dropped: `qcin.org` tender listing page and two other QCI URLs
returned 404 (site restructured since indexed), and `daman.nic.in` refused
connection outright. `data.gov.in` didn't surface a direct XLSX sample via
search — synthesize one manually if XLSX ingestion needs testing before real
QCI spreadsheets are available.

## Second batch (19 Aug 2026) — for throughput testing at larger scale

16 more real government PDFs, downloaded via `scripts/bulk_download_samples.ps1`,
spread across the RFP's actual document types (MoU, EoI/Proposal, Tender/Work
Order, Agreement) plus more circulars for OCR variety. 4 of 20 attempted failed
honestly (404s / connection refused) and were not kept.

| File | Source domain | Type |
|---|---|---|
| `mou_mea_jordan_manpower.pdf` | mea.gov.in | MoU |
| `mou_dcmsme_textile.pdf` | dcmsme.gov.in | MoU |
| `mou_npc_kpmg.pdf` | npcindia.gov.in | MoU |
| `eoi_expert_consultants_2025.pdf` | cdnbbsr.s3waas.gov.in | EoI/Proposal |
| `eoi_kerala_mission1000.pdf` | industry.kerala.gov.in | EoI/Proposal |
| `eoi_nimsme_empanelment.pdf` | nimsme.gov.in | EoI/Proposal |
| `eoi_upeida_consultant_ca.pdf` | upeida.up.gov.in | EoI/Proposal |
| `tender_mea_courier.pdf` | mea.gov.in | Tender |
| `tender_model_document_goods.pdf` | eprocure.gov.in | Tender (model/template doc) |
| `tender_tnpcb_tccl.pdf` | tnpcb.gov.in | Tender |
| `tender_newmangalore_dredging.pdf` | newmangaloreport.gov.in | Tender |
| `agreement_sla_manpower_gem.pdf` | finance.py.gov.in | Agreement/SLA |
| `agreement_consultancy_template.pdf` | startupindia.gov.in | Agreement |
| `circular_cbic_2015.pdf` | upload.indiacode.nic.in | Circular (2015, OCR candidate) |
| `circular_dopt_estt_2013.pdf` | documents.doptcirculars.nic.in | Circular |
| `circular_pci_2014.pdf` | pci.nic.in | Circular |

Failed (404/connection refused, not kept): `mou_vvgnli_labour_2023.pdf`,
`mou_cbwe_workers_education.pdf`, `agreement_legalaffairs_contract.pdf`,
`agreement_transmission_service.pdf`.

**Total corpus (before third batch): 21 documents, ~20MB.**

## Third batch (19 Aug 2026) — closing the Agreement-type coverage gap

Agreement was the thinnest-covered type (2 docs vs. 4-6 for the others),
directly affecting how well the Agreement templates' AI-expanded sections
("for tone/structure only") could ground themselves. 3 attempted, 1 dead
link (mohfw.gov.in, 404), 2 real docs added:

| File | Source domain | Type |
|---|---|---|
| `agreement_sla_housekeeping_gem.pdf` | finance.py.gov.in | Agreement/SLA (housekeeping — different variant from the manpower SLA already in the corpus) |
| `agreement_dgshipping_contract_mgmt.pdf` | dgma.gov.in | Contract management procedure (DG Shipping) |

**Total corpus (before fourth batch): 23 documents, ~20MB.**

## Fourth batch (21 Aug 2026) — closing Licensing/IP and AMC coverage gaps

The two templates with zero real-document grounding, flagged directly during
a functional-completeness review: Licensing Agreement and Work Order — AMC.
3 of 4 attempted downloads were real; one (`startupindia.gov.in`'s "Leave and
License Agreement") 404'd despite showing in search results — the URL
resolved to an HTML error page, not a PDF, caught by checking the file
header before keeping it.

| File | Source domain | Type |
|---|---|---|
| `agreement_license_smartcity.pdf` | megurban.gov.in | Licensing (35-page draft commercial licence agreement, Shillong Smart City Ltd.) |
| `amc_rrcat_annexure.pdf` | rrcat.gov.in | AMC (standard terms & conditions annexure) |
| `amc_keralapolice.pdf` | keralapolice.gov.in | AMC |

Failed (404, not kept): `startupindia.gov.in`'s Leave and License Agreement template.

**Total corpus: 26 documents, ~22MB.**
