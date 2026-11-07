# Threat model: ArthurMask

## What this project does and where untrusted input enters

A desktop privacy gate for lawyers (Windows and macOS). The lawyer drops a court or client document (Word `.docx`,
Turkish court UYAP `.udf` = zip + XML, PDF, scanned PDF or image, `.txt`/`.md`). ArthurMask detects personal data
(names, companies, Turkish ID and tax numbers, IBAN, addresses, phones, e-mails, birth dates, file numbers, plates)
with rules plus a local GLiNER model, replaces each value with a label such as `{{KİŞİ-01}}`, and keeps the
real↔label mapping in an encrypted per-matter vault. Claude Desktop reaches the documents only through a local MCP
bridge (`arthur-mask-kopru`, stdio): `belge_getir` returns masked text, `teslim` un-masks Claude's answer locally.
An exit gate (`arthur_mask/cikis.py`) re-scans every response sent to Claude against all real values of the active
matter and replaces any occurrence with its label.

**The one promise:** a client's real personal data never appears in anything sent to Claude and never leaves the
machine. Untrusted input:

- **Documents** (any of the formats above), written by anyone: opposing counsel, courts, clients. Assume crafted
  files (unusual XML namespaces, entities, CDATA, zip bombs, huge images, many PDF pages).
- **MCP tool arguments** from Claude (`kimlik`, `degisiklikler`, `metin`, `baslik`): the model can be steered by
  prompt injection inside the documents it reads.
- **Local HTTP** on `127.0.0.1:47831` (`arthur_mask/sunucu.py`): any web page the user visits can send requests to
  it; the API requires a per-user token header and checks Host and Origin.
- **The daily update check** (`guncelleme.py`, GitHub releases JSON; it only shows a link).

## Components that matter most / least

- **Most:** the exit gate (`cikis.py`) and every path that builds text for Claude (`islem.py` `mcp_*`,
  `docx_yapi.claude_gorunumu`); parsers whose output is masked (`docx.py`, `udf.py`, `belgeler.py`, `goruntu.py`):
  any text a parser shows Claude but the masker did not see is critical; the vault and key (`kasa.py`,
  `anahtar.py`, `depo.py`); the local server and token (`sunucu.py`, `baslat.py`); the masked image PDFs for scans.
- **Medium:** detection quality (`motor.py`, `tanimlayicilar.py`, `semantik.py`): a value that is never detected is
  not in the vault, so the exit gate cannot catch it either; report concrete leak patterns, not general recall.
- **Least:** `degerlendirme/` (offline evaluation scripts), `paketleme/` (build scripts), `ornekler/`, `tests/`.

## How to exercise it

- `python -m pytest -q` (the image sets `ARTHUR_MASK_ANA_ANAHTAR` and has the GLiNER and OCR models offline).
- CLI: `arthur-mask maskele <file>` / `arthur-mask geri-ac <file>`; bridge: `arthur-mask-kopru` (stdio MCP).
- `tests/test_servis_kopru.py` drives the full flow (upload, review, MCP calls, local HTTP) with made-up data;
  `tests/test_uctan_uca_stdio.py` checks the raw bytes sent over stdio; `tests/test_cikis.py` the exit gate.

## How we rate severity

- **Critical:** a real value (or unmasked document text) reaches any MCP response, tool description, error message
  or file name sent to Claude; a web page or another OS account can read the vault, unmasked answers, the token or
  the recovery code.
- **High:** a parser/extraction mismatch that sends unmasked text for a whole document type; an exit-gate bypass for
  a whole class of values (all e-mails, all phone numbers in one notation); the bridge accepting un-reviewed
  documents as ready.
- **Medium:** single format variants that slip the gate; real values at rest outside the encrypted vault;
  identifying metadata left in masked copies.
- **Low:** crashes or memory exhaustion from crafted local files, log hygiene, update and signing posture.

## Anything to leave alone

- Any process running as the same OS user can obtain the key (Windows DPAPI user scope, macOS login keychain):
  by design; the OS account owner is trusted.
- Dates and amounts are deliberately not masked; facts that are not identifiers are not masked.
- OCR cannot read handwriting, signatures, stamps or QR codes; the README tells the lawyer to check scanned output.
- What Claude/Anthropic does with masked text, and what the user pastes into the chat themselves, are out of scope.
