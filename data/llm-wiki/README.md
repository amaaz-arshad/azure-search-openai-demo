# LLM Wiki Input

Put compiled Markdown wiki pages here before uploading them to Azure Blob Storage.

Expected local layout:

```text
data/llm-wiki/<chatbot>/wiki/index.md
data/llm-wiki/<chatbot>/wiki/log.md
data/llm-wiki/<chatbot>/wiki/concepts/*.md
data/llm-wiki/<chatbot>/wiki/entities/*.md
data/llm-wiki/<chatbot>/wiki/sources/*.md
```

Upload a wiki with:

```powershell
python app/backend/upload_llm_wiki.py <chatbot>
```

The upload preserves the relative Markdown paths under:

```text
__llm_wiki__/<chatbot>/wiki/
```

Raw PDFs, XML, JSON, DOCX, and similar source files should stay immutable in a separate raw folder until they are compiled into Markdown pages.

To compile raw source files directly from this repo's `content/<chatbot>/` folders and upload the resulting Markdown wiki to blob storage:

```powershell
python app/backend/compile_llm_wiki.py --chatbot <chatbot> --local-content-root content --overwrite
```

Very large source files are split into multiple `sources/*-part-NNN.md` wiki pages automatically. Tune `--raw-chunk-chars`, `--max-source-pages`, and `--max-chunks-per-wiki-page` only when a source file is unusually large.
