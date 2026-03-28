from text_utils import preprocess_md
with open("Mol_Plant_2017_Zhu.md", "r", encoding="utf-8") as f:
    raw_md = f.read()
processed_md = preprocess_md(raw_md)
with open("Mol_Plant_2017_Zhu_processed.md", "w", encoding="utf-8") as f:
    f.write(processed_md)