# Statement samples

**The PDFs themselves are not in this repository.** `.gitignore` excludes
`samples/*.pdf`, because they are real exports from BAC, LAFISE and BANPRO
containing real account numbers and the names of people who paid the business.
A git repository is forever; one accidental change of visibility would publish
them permanently.

They still need to exist on any machine where you work on the parsers, because
`tests/test_parsers.py` asserts the exact transactions in each file — that is
how a change to a bank's layout shows up as a failing test rather than as a
silently wrong reconciliation. When the files are absent those tests skip, and
the rest of the suite still runs, which is what happens in CI.

Put them here, with these names:

| File | Bank | Currency | Extraction |
|---|---|---|---|
| `bac cordoba aug-11.pdf` | BAC | NIO | OCR (no embedded fonts) |
| `bac dollars Aug-11.pdf` | BAC | USD | OCR |
| `lafise cordoba Aug-11.pdf` | LAFISE | NIO | text |
| `lafise cordoba Aug-20.pdf` | LAFISE | NIO | text |
| `lafise dollar Aug-11.pdf` | LAFISE | USD | text |
| `lafise dollar Aug-20.pdf` | LAFISE | USD | text |
| `Banpro - Cordoba Aug-20.pdf` | BANPRO | NIO | text |
| `Banpro - USD Aug-20.pdf` | BANPRO | USD | text |

There is no FICOHSA sample, which is why there is no FICOHSA parser.

To check the files are being ignored as intended:

```bash
git check-ignore -v samples/*.pdf     # every line should print a rule
git status --short samples/           # should show nothing
```
