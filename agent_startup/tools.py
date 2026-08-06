"""Définitions d'outils pour l'agent Startup agentique.

Les fonctions sous-jacentes (recherche web, scraping, mémoire, enregistrement)
sont partagées avec agent_benchmark — la seule différence est la description
présentée au LLM, orientée startups agritech plutôt que benchmark concurrentiel.
"""

# Réexporte les fonctions de benchmark (logique identique, réutilisation maximale)
from agent_benchmark.tools import (
    outil_enregistrer_entreprise,
    outil_lire_page,
    outil_rechercher_memoire,
    outil_rechercher_web,
)

__all__ = [
    "outil_rechercher_web",
    "outil_lire_page",
    "outil_rechercher_memoire",
    "outil_enregistrer_entreprise",
    "DEFINITIONS_OUTILS_STARTUP",
]


DEFINITIONS_OUTILS_STARTUP = [
    {
        "type": "function",
        "function": {
            "name": "rechercher_memoire",
            "description": (
                "Cherche si une startup agritech est déjà connue en mémoire (études précédentes) "
                "avant de chercher sur le web — à utiliser en premier."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {
                        "type": "string",
                        "description": "Nom de la startup ou sujet à retrouver en mémoire",
                    }
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rechercher_web",
            "description": (
                "Cherche des startups agritech marocaines sur le web : listes, levées de fonds, "
                "incubateurs, médias spécialisés, solutions numériques agricoles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requete": {
                        "type": "string",
                        "description": "La requête de recherche (ex: 'startup agritech Maroc irrigation connectée 2024')",
                    }
                },
                "required": ["requete"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lire_page",
            "description": (
                "Lit le contenu texte d'une page startup à partir de son NUMÉRO [n], "
                "tel qu'affiché par rechercher_web. Obligatoire avant tout enregistrement. "
                "N'accepte jamais une URL tapée directement — utilise uniquement un numéro "
                "déjà vu dans les résultats d'une recherche précédente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "Le numéro [n] du résultat à lire, tel qu'affiché par rechercher_web.",
                    }
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enregistrer_entreprise",
            "description": (
                "Enregistre une startup agritech identifiée avec ses informations, UNIQUEMENT si "
                "trouvées dans une page réellement lue via lire_page (jamais depuis ta mémoire seule). "
                "Inclure stade_financement, fondateurs, innovations si présents dans le texte source."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nom": {
                        "type": "string",
                        "description": "Nom exact de la startup (pas du site éditeur ou de l'incubateur)",
                    },
                    "secteur": {
                        "type": "string",
                        "description": "Secteur agritech précis (ex: irrigation connectée, marketplace agricole, traçabilité)",
                    },
                    "description": {"type": "string"},
                    "site_web": {"type": "string"},
                    "annee_fondation": {"type": "string"},
                    "fondateurs": {"type": "array", "items": {"type": "string"}},
                    "stade_financement": {
                        "type": "string",
                        "description": "pre-seed, seed, série A, série B, etc. — uniquement si explicitement mentionné",
                    },
                    "financement_leve": {
                        "type": "string",
                        "description": "Montant total levé si explicitement mentionné dans la source",
                    },
                    "investisseurs": {"type": "array", "items": {"type": "string"}},
                    "produits_services": {"type": "array", "items": {"type": "string"}},
                    "technologies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "valeur": {"type": "string"},
                                "source_url": {"type": "string"},
                                "date_collecte": {"type": "string"},
                                "confiance": {"type": "number"},
                            },
                        },
                    },
                    "innovations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "valeur": {"type": "string"},
                                "source_url": {"type": "string"},
                                "date_collecte": {"type": "string"},
                                "confiance": {"type": "number"},
                            },
                        },
                    },
                    "investissements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "valeur": {"type": "string"},
                                "source_url": {"type": "string"},
                                "date_collecte": {"type": "string"},
                                "confiance": {"type": "number"},
                            },
                        },
                    },
                    "score_pertinence": {
                        "type": "number",
                        "description": "0 à 1 — degré de pertinence agritech marocaine (0.8+ = startup clairement identifiée)",
                    },
                    "source_url": {"type": "string"},
                },
                "required": ["nom", "source_url"],
            },
        },
    },
]
