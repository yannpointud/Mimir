"""
Test Document Generator for Mimir RAG Pipeline.
Generates realistic enterprise documents (PDF/DOCX) using Mistral API.
Output is saved to data/generated_documents/.

Usage:
    python scripts/generate_test_documents.py

Requires:
    - MISTRAL_API_KEY environment variable (from backend/.env)
    - pip install python-docx fpdf mistralai
"""

import os
import sys
import random
import time
from docx import Document
from fpdf import FPDF
from mistralai.client import MistralClient
from mistralai.models.chat_completion import ChatMessage

# --- CONFIGURATION ---
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

NUM_DOCUMENTS = 50  # Number of documents to generate
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "generated_documents")
PAUSE_BETWEEN_FILES = 1

# --- Themes and subjects (extended lists for more diversity) ---
COMPANY_NAME = "Innovatech Solutions"
PROJECT_NAMES = [
    "Project Phoenix",
    "QuantumLeap AI",
    "DataStream Pro",
    "Helios Initiative",
    "Project Nebula",
    "Odyssey Platform",
    "Titan Security Core",
    "Hyperion Analytics",
    "Vanguard Integration",
    "Project Chimera",
    "Aether Framework",
    "Project Stardust",
    "Omega Protocol",
    "CyberLogos Initiative",
    "Project Galileo",
]
PRODUCT_NAMES = [
    "Innovatech Secure Suite",
    "CogniFlow Analytics",
    "ConnectSphere API",
    "PulseGuard Monitor",
    "Synapse CRM",
    "Quantum Ledger",
    "Echo Vault Storage",
    "Visionary AI Toolkit",
    "DataWeave ETL",
    "Orion BI Dashboard",
]
DEPARTMENTS = [
    "R&D",
    "Marketing",
    "Ressources Humaines",
    "Opérations",
    "Finance",
    "Legal & Compliance",
    "Customer Success",
    "Cybersecurity",
    "Product Management",
    "Sales",
]
DOC_TYPES = [
    "Rapport Technique Détaillé",
    "Compte Rendu de Réunion Stratégique",
    "Spécification Fonctionnelle Complète",
    "Politique d'Entreprise Officielle",
    "Analyse de Marché Concurrentiel",
    "Guide Utilisateur Avancé",
    "Rapport Financier Trimestriel (QBR)",
    "Post-Mortem d'Incident",
    "Audit de Sécurité",
    "Plan de Projet",
    "Documentation API",
    "Proposition Commerciale",
    "Guide d'Onboarding pour Nouveaux Employés",
    "Analyse des Risques",
    "Communiqué de Presse",
]

# Initialize Mistral client
if not MISTRAL_API_KEY:
    print("Error: MISTRAL_API_KEY environment variable is not set.")
    print("Set it with: export MISTRAL_API_KEY=your_key_here")
    sys.exit(1)

try:
    client = MistralClient(api_key=MISTRAL_API_KEY)
except Exception as e:  # noqa: BLE001 - CLI boundary: report any failure and exit non-zero
    print(f"Error initializing Mistral client. Check your API key. Error: {e}")
    sys.exit(1)


def generate_long_content(doc_type, subject):
    """Generate a longer, more detailed document content."""

    prompt = f"""
    Rédige un document d'entreprise complet et professionnel pour la société "{COMPANY_NAME}".

    Type de document : "{doc_type}"
    Sujet : "{subject}"

    Le document doit être substantiel, entre 500 et 1500 mots (environ 1 à 3 pages).
    Invente une structure de document logique et détaillée avec plusieurs sections et sous-sections, en utilisant le formatage Markdown simple (ex: # Titre, ## Section, ### Sous-section).
    
    Le contenu doit être plausible, riche en détails, et refléter un contexte d'entreprise réaliste.
    Inclus des éléments comme des listes à puces, des paragraphes explicatifs, et des conclusions claires.
    Commence par un en-tête simple incluant un titre, un auteur fictif, et une date.
    """

    print(f"  > Envoi de la requête à l'API Mistral pour un document long : {doc_type} - {subject}")

    try:
        messages = [ChatMessage(role="user", content=prompt)]
        chat_response = client.chat(
            model=MISTRAL_MODEL,
            messages=messages,
        )
        return chat_response.choices[0].message.content
    except Exception as e:  # noqa: BLE001 - CLI boundary: skip the document on any API failure
        print(f"  !!! Erreur lors de l'appel à l'API Mistral : {e}")
        return None


def create_docx(content, filepath):
    """Create a .docx file from the text content."""
    doc = Document()
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("* "):
            doc.add_paragraph(line, style="List Bullet")
        elif line:
            doc.add_paragraph(line)
    doc.save(filepath)


def create_pdf(content, filepath):
    """Create a .pdf file directly from the text content."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            pdf.set_font("Arial", "B", 18)
            pdf.multi_cell(0, 10, line[2:].encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(10)
        elif line.startswith("## "):
            pdf.set_font("Arial", "B", 14)
            pdf.multi_cell(0, 8, line[3:].encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(8)
        elif line.startswith("### "):
            pdf.set_font("Arial", "I", 12)
            pdf.multi_cell(0, 6, line[4:].encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(6)
        elif line.startswith("* "):
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 6, f"  - {line[2:]}".encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(1)
        elif line:
            pdf.set_font("Arial", "", 12)
            pdf.multi_cell(0, 6, line.encode("latin-1", "replace").decode("latin-1"))
            pdf.ln(4)
        else:
            pdf.ln(4)

    pdf.output(filepath)


def main():
    """Generate every test document."""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Dossier '{OUTPUT_DIR}' créé.")

    for i in range(NUM_DOCUMENTS):
        doc_type = random.choice(DOC_TYPES)
        subject = f"{random.choice(DEPARTMENTS)} - {random.choice(PROJECT_NAMES)}"  # Simpler, more varied subject logic

        print(f"\n--- Génération du document {i + 1}/{NUM_DOCUMENTS} ---")
        content = generate_long_content(doc_type, subject)

        if not content:
            print("  !!! Échec de la génération de contenu, passage au suivant.")
            continue

        base_filename = f"{doc_type}_{subject}".replace(" ", "_").replace("/", "_").replace(":", "")

        # --- Random choice of the output format ---
        output_format = random.choice(["docx", "pdf"])

        if output_format == "docx":
            filepath = os.path.join(OUTPUT_DIR, f"{base_filename}.docx")
            print(f"  > Création du fichier DOCX : {filepath}")
            create_docx(content, filepath)
        else:  # pdf
            filepath = os.path.join(OUTPUT_DIR, f"{base_filename}.pdf")
            print(f"  > Création du fichier PDF : {filepath}")
            create_pdf(content, filepath)

        print(f"  > Pause de {PAUSE_BETWEEN_FILES} seconde(s)...")
        time.sleep(PAUSE_BETWEEN_FILES)

    print(f"\n--- Terminé ! {NUM_DOCUMENTS} documents ont été générés dans '{OUTPUT_DIR}'. ---")


if __name__ == "__main__":
    main()
