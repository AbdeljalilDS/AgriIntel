"""Export des résultats en Excel et PDF."""
import io

import pandas as pd
from fpdf import FPDF

from core.models import EntiteAnalysee


def entites_vers_dataframe(entites: list[EntiteAnalysee]) -> pd.DataFrame:
    lignes = []
    for e in entites:
        lignes.append({
            "Nom": e.nom, "Secteur": e.secteur or "", "Description": e.description or "",
            "Produits/services": ", ".join(e.produits_services),
            "Technologies": ", ".join(e.technologies),
            "Certifications": ", ".join(e.certifications),
            "Score": e.score_pertinence if e.score_pertinence is not None else "",
            "Source": e.source_url,
        })
    return pd.DataFrame(lignes)


def exporter_excel(entites: list[EntiteAnalysee]) -> bytes:
    df = entites_vers_dataframe(entites)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Résultats")
    return buffer.getvalue()


def _nettoyer_pour_pdf(texte: str) -> str:
    remplacements = {"’": "'", "‘": "'", """: '"', """: '"', "–": "-", "—": "-", "…": "..."}
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    return texte.encode("latin-1", errors="replace").decode("latin-1")


def _ecrire_ligne(pdf: FPDF, texte: str, hauteur: float = 6) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, hauteur, texte)


def exporter_pdf(titre: str, entites: list[EntiteAnalysee], rapport_markdown: str = "") -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    _ecrire_ligne(pdf, _nettoyer_pour_pdf(titre), 10)
    pdf.ln(4)

    if rapport_markdown:
        pdf.set_font("Helvetica", "", 10)
        for ligne in rapport_markdown.split("\n"):
            ligne = _nettoyer_pour_pdf(ligne)
            if not ligne.strip():
                pdf.ln(3)
                continue
            if ligne.startswith("## "):
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 13)
                _ecrire_ligne(pdf, ligne.replace("## ", ""), 8)
                pdf.set_font("Helvetica", "", 10)
            elif ligne.startswith("# "):
                pdf.set_font("Helvetica", "B", 14)
                _ecrire_ligne(pdf, ligne.replace("# ", ""), 8)
                pdf.set_font("Helvetica", "", 10)
            elif ligne.startswith("|"):
                continue
            else:
                _ecrire_ligne(pdf, ligne, 6)
        pdf.ln(6)

    pdf.set_font("Helvetica", "B", 13)
    _ecrire_ligne(pdf, f"Détail des {len(entites)} entités", 8)
    pdf.set_font("Helvetica", "", 10)
    for e in entites:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        _ecrire_ligne(pdf, _nettoyer_pour_pdf(e.nom), 6)
        pdf.set_font("Helvetica", "", 9)
        if e.secteur:
            _ecrire_ligne(pdf, _nettoyer_pour_pdf(f"Secteur : {e.secteur}"), 5)
        if e.description:
            _ecrire_ligne(pdf, _nettoyer_pour_pdf(f"Description : {e.description}"), 5)
        _ecrire_ligne(pdf, _nettoyer_pour_pdf(f"Source : {e.source_url}"), 5)

    return bytes(pdf.output())
