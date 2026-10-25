"""La documentazione pubblicata su GitHub resta coerente: link, immagini, ancore, riferimento al paper, licenza."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
READMES = ("README.md", "README.it.md")
DOI = "10.3905/jwm.2024.1.227"
FENCE = re.compile(r"^(```|~~~).*?^\1\s*$", re.S | re.M)


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def prose(text: str) -> str:
    """Testo senza blocchi di codice né codice inline (dove link e simboli non sono documentazione)."""
    return re.sub(r"`[^`\n]*`", "", FENCE.sub("", text))


def slug(heading: str) -> str:
    """Ancora che GitHub genera da un titolo: minuscolo, senza punteggiatura, spazi come trattini."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("*", "")
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in FENCE.sub("", text).splitlines():
        match = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not match:
            continue
        base = slug(match.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


def targets(text: str) -> list[str]:
    body = prose(text)
    found = re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", body)
    found += re.findall(r"""(?:src|href)=["']([^"']+)["']""", body)
    return found


@pytest.mark.parametrize("name", READMES)
def test_readme_links_images_and_anchors_resolve(name):
    text = read(name)
    own = anchors(text)
    problems = []
    for target in targets(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, fragment = target.partition("#")
        if not path:
            if fragment not in own:
                problems.append(f"ancora #{fragment} senza titolo")
            continue
        file = ROOT / path
        if not file.exists():
            problems.append(f"{target}: il file non esiste")
        elif fragment and file.suffix == ".md" and fragment not in anchors(file.read_text(encoding="utf-8")):
            problems.append(f"{target}: l'ancora non esiste")
    assert not problems, f"{name}: " + "; ".join(problems)


@pytest.mark.parametrize("name", READMES)
def test_readme_is_ready_to_publish_without_placeholders(name):
    text = read(name)
    for placeholder in ("YOUR_USER", "YOUR-APP", "your-username", "LICENSE file of your choice", "Aggiungi un file `LICENSE`",
                        "TODO", "FIXME", "lorem"):
        assert placeholder not in text, f"{name}: segnaposto «{placeholder}»"
    assert "docs/images/hero.png" in text, "una buona prima impressione: lo schermo iniziale in cima"


def test_the_screenshots_are_real_images_of_reasonable_size():
    images = sorted((ROOT / "docs" / "images").iterdir())
    assert len(images) >= 10
    for image in images:
        head = image.read_bytes()[:8]
        assert head.startswith(b"\x89PNG") or head.startswith(b"GIF8"), f"{image.name} non è un'immagine"
        assert image.stat().st_size < 2_000_000, f"{image.name}: troppo pesante per un README"
    used = set(re.findall(r"docs/images/([\w.-]+)", read("README.md")))
    assert used and all((ROOT / "docs" / "images" / name).exists() for name in used)


def test_the_paper_is_cited_in_full_wherever_the_model_is_presented():
    for name in (*READMES, "CITATION.cff", "docs/AUDIT.md"):
        text = read(name)
        assert DOI in text and "Pomante" in text and "Cucurachi" in text, f"{name}: riferimento al paper incompleto"
    english = read("README.md")
    assert "## The paper" in english and "### Citing" in english and "### Paper → code" in english
    bibtex = re.search(r"@article\{pomante2024plugandplay,(.*?)\n\}", english, re.S).group(1)
    for field in ("volume  = {26}", "number  = {4}", "pages   = {33--48}", f"doi     = {{{DOI}}}", "Ugo", "Vincenzo", "Paolo Antonio"):
        assert field in bibtex, f"BibTeX: manca «{field}»"
    assert "The Journal of Wealth Management" in bibtex and "year    = {2024}" in bibtex
    assert "## Il paper" in read("README.it.md")


def test_every_mention_of_the_paper_links_to_its_doi_or_to_the_paper_section():
    """Ogni volta che il README presenta il modello il lettore può arrivare al riferimento completo."""
    for name, section in (("README.md", "#the-paper"), ("README.it.md", "#il-paper")):
        text = read(name)
        assert f"https://doi.org/{DOI}" in text and section in text


def test_license_is_mit_and_consistent_everywhere():
    licence = read("LICENSE")
    assert licence.startswith("MIT License") and "Permission is hereby granted, free of charge" in licence
    assert "license: MIT" in read("CITATION.cff")
    assert "[MIT License](LICENSE)" in read("README.md") and "[MIT](LICENSE)" in read("README.it.md")
    assert "static/fonts/OFL.txt" in read("README.md"), "il font Inter mantiene la propria licenza"


def test_the_repository_address_is_the_same_in_every_file():
    owners = set()
    for name in (*READMES, "CITATION.cff"):
        owners |= set(re.findall(r"github\.com/([\w.-]+)/goalga", read(name)))
    assert owners == {"DaValz"}, owners


def test_citation_file_describes_the_software_and_the_paper():
    text = read("CITATION.cff")
    for field in ("cff-version: 1.2.0", "title:", "authors:", "repository-code:", "references:", "type: article",
                  "volume: 26", "start: 33", "end: 48", f'doi: "{DOI}"'):
        assert field in text, f"CITATION.cff: manca «{field}»"


def test_citation_file_is_valid_yaml_and_matches_the_package_version():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(read("CITATION.cff"))
    assert data["references"][0]["authors"][2]["family-names"] == "Cucurachi"
    from goalga import __version__
    assert data["version"] == __version__, "la versione del pacchetto e quella della citazione coincidono"


def test_no_personal_paths_or_missing_folders_are_mentioned_in_the_docs():
    for name in (*READMES, "docs/AUDIT.md", "docs/DESIGN.md"):
        text = read(name)
        assert not re.search(r"C:\\Users\\(?!<)", text) and "OneDrive" not in text, f"{name}: percorso personale"
        assert "_backup_originale" not in text, f"{name}: cartella che non fa parte del repository"
