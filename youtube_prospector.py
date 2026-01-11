#!/usr/bin/env python3
"""
YouTube Prospector V1 - Gemini Product Edition
Transforme la recherche de clients YouTube en un processus structuré et scoré.
"""

import os
import sys
import json
import csv
import time
import subprocess
from datetime import datetime, timedelta
from groq import Groq
import io

# --- CONFIGURATION ---
GROQ_MODEL_ID = "llama-3.3-70b-versatile" 

def get_groq_client(api_key=None):
    """Configure et retourne le client Groq."""
    if not api_key:
        api_key = os.environ.get("GROQ_API_KEY")
    
    if not api_key:
        # En mode CLI, on exit. En mode lib, on pourra gérer l'erreur plus haut.
        print("❌ CRITIQUE : Variable GROQ_API_KEY manquante.")
        print("   Exportez-la : export GROQ_API_KEY='votre_clé'")
        return None
    return Groq(api_key=api_key)

def call_llm(prompt: str, client: Groq) -> str:
    """Envoyer un prompt à Groq et récupérer le texte pur."""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL_ID,
            messages=[
                {"role": "system", "content": "You are a JSON-only response bot."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1 # Plus précis pour le JSON
        )
        return response.choices[0].message.content
    except Exception as e:
        # Gestion propre des erreurs API
        print(f"\n⚠️ Erreur Groq: {e}")
        return ""

# --- UTILS DE DATE & FORMAT ---
def is_video_recent(date_str: str, days: int = 30) -> bool:
    """Filtre STRICT : vidéo <= 30 jours."""
    if not date_str or len(date_str) != 8:
        return False
    try:
        upload_date = datetime.strptime(date_str, "%Y%m%d")
        cutoff_date = datetime.now() - timedelta(days=days)
        return upload_date >= cutoff_date
    except ValueError:
        return False

def format_date(date_str: str) -> str:
    """Format JJ/MM/AAAA."""
    if len(date_str) == 8:
        return f"{date_str[6:8]}/{date_str[4:6]}/{date_str[:4]}"
    return "Date inconnue"

# --- YOUTUBE & DATA ---
def get_video_details(video_url: str) -> dict:
    """Récupère métadonnées complètes incluant abonnés."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        video_url,
        "--dump-json",
        "--no-download",
        "--skip-download",
        "--socket-timeout", "10",
        "--no-warnings"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            
            # Récupération en cascade des abonnés
            subs = data.get("uploader_subscriber_count")
            if subs is None:
                subs = data.get("channel_follower_count")
            if subs is None:
                subs = data.get("subscriber_count")
                
            return {
                "title": data.get("title", ""),
                "channel": data.get("channel", data.get("uploader", "")),
                "description": data.get("description", ""),
                "view_count": data.get("view_count", 0),
                "like_count": data.get("like_count", 0),
                "duration": data.get("duration", 0),
                "upload_date": data.get("upload_date", ""),
                "subscriber_count": subs,
                "url": video_url
            }
    except Exception:
        pass
    return {}

def prequalify(details: dict, subs_min: int = 0, subs_max: int = 500000) -> tuple[bool, str, list]:
    """Hard gates pour disqualifier AVANT appel IA."""
    subs = details.get("subscriber_count")
    duration = details.get("duration", 0)
    channel = details.get("channel", "")

    red_flags = []
    
    # Règle 1: Taille de la chaîne (Min/Max dynamic)
    if subs is not None:
        if subs > subs_max:
            return False, f"Chaîne trop grosse (>{subs_max})", ["too_big"]
        if subs < subs_min:
             return False, f"Chaîne trop petite (<{subs_min})", ["too_small"]
        
    # Règle 2: Masterclass > 1h
    if duration and duration >= 3600:
        return False, "Format masterclass (>60min)", ["masterclass"]
        
    # Règle 3: Auto-generated
    if " - Topic" in channel or "Auto-generated" in details.get("description", ""):
        return False, "Contenu auto-généré/Topic", ["auto_generated"]

    return True, "", []

def search_search_videos(query: str, max_results: int) -> list[dict]:
    """Recherche rapide initiale."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        f"ytsearch{max_results}:{query}",
        "--dump-json",
        "--no-download",
        "--skip-download",
        "--flat-playlist",
        "--no-warnings",
        "--dateafter", "now-30days", # Pré-filtre large
        "--extractor-args", "youtube:player_skip=configs",
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    data = json.loads(line)
                    videos.append({
                        "id": data.get("id"),
                        "title": data.get("title"),
                        "url": data.get("url", f"https://www.youtube.com/watch?v={data.get('id')}"),
                        "channel": data.get("uploader", "Inconnu") # flat playlist use uploader
                    })
                except json.JSONDecodeError:
                    continue
        return videos
    except subprocess.TimeoutExpired:
        print("❌ Timeout recherche yt-dlp.")
        return []
    except Exception as e:
        print(f"❌ Erreur recherche: {e}")
        return []

# --- ANALYSE IA ---
def analyze_candidate(details: dict, lang_version: str, client: Groq) -> dict:
    """Logique de scoring et génération de message via Groq."""
    
    # Textes dynamiques selon la langue
    if lang_version == "en":
        role_desc = "You are an expert YouTube strategist and personalized outreach specialist."
        task = "Analyze this channel for video editing service needs."
        lang_instruction = "Write the prospecting message in ENGLISH."
    else:
        role_desc = "Tu es un expert en stratégie YouTube et prospection commerciale."
        task = "Analyse cette chaîne pour détecter des besoins en montage vidéo."
        lang_instruction = "Rédige le message de prospection en FRANÇAIS."

    prompt = f"""
{role_desc}
{task}

INFO CANDIDAT:
- Chaîne: {details.get('channel')}
- Vidéo: {details.get('title')}
- Durée: {details.get('duration')}s
- Vues: {details.get('view_count')}
- Abonnés: {details.get('subscriber_count', 'N/A')}
- Date: {details.get('upload_date')}
- Description partielle: {details.get('description', '')[:600]}...

SCORING STRICT (Base 0 pts):
+20 pts : Créateur individuel / ton "solo" (ex: "my channel", vlog).
+15 pts : Durée idéale (8 à 30 min).
+10 pts : Vues modérées (1k - 50k).
+15 pts : Signes de montage perfectible (mentionnés dans desc ou format long sans timestamps).

MALUS & CAPS (Règles strictes):
-30 pts : Chaîne très pro (branding TV, clips musicaux, bandes annonces).
-50 pts : Abonnés >= 500k (Même si passé filtres).
CAP MAX 60 : Si Abonnés >= 200k.
CAP MAX 50 : Si vidéo déjà très "polished" / masterclass.

RÈGLE D'OR : needs_editor = true UNIQUEMENT si lead_score >= 70.

FORMAT DE RÉPONSE ATTENDU (JSON PUR):
{{
  "lead_score": int,
  "needs_editor": boolean, 
  "reason": "1-2 phrases max expliquant la décision",
  "evidence": ["Preuve précise 1 (ex: durée 12min)", "Preuve précise 2 (ex: créateur solo)"],
  "prospecting_message": "Message court et personnalisé (si qualifié)",
  "red_flags": ["Liste", "des", "points", "négatifs"],
  "language_version": "{lang_version}"
}}
Obligation : 'evidence' doit contenir exactement 2 faits tirés des infos fournies.

{lang_instruction}
Réponds UNIQUEMENT le JSON.
    """
    
    raw_response = call_llm(prompt, client)
    
    # Parsing robuste
    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        
        parsed = json.loads(cleaned.strip())
        
        # Validation structure
        return {
            "lead_score": parsed.get("lead_score", 0),
            "needs_editor": parsed.get("needs_editor", False),
            "reason": parsed.get("reason", "N/A"),
            "evidence": parsed.get("evidence", []),
            "prospecting_message": parsed.get("prospecting_message", "N/A"),
            "red_flags": parsed.get("red_flags", []),
            "language_version": lang_version
        }
    except Exception:
        return {
            "lead_score": 0,
            "needs_editor": False,
            "reason": "Erreur parsing JSON IA",
            "evidence": [],
            "prospecting_message": "N/A",
            "red_flags": ["json_invalid"],
            "language_version": lang_version
        }

# --- CSV GENERATION ---
def generate_csv_string(results: list, query: str) -> str:
    """Génère le contenu CSV en mémoire."""
    output = io.StringIO()
    fieldnames = [
        "run_timestamp", "niche", "query_used", "channel", 
        "video_title", "video_url", "upload_date", "subscriber_count", 
        "view_count", "lead_score", "needs_editor", 
        "language_version", "reason", "evidence", "prospecting_message", "red_flags"
    ]
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for res in results:
        writer.writerow({
            "run_timestamp": timestamp,
            "niche": query,
            "query_used": query,
            "channel": res.get("channel"),
            "video_title": res.get("video_title"),
            "video_url": res.get("url"),
            "upload_date": res.get("upload_date"),
            "subscriber_count": res.get("subscriber_count"),
            "view_count": res.get("view_count"),
            "lead_score": res.get("analysis", {}).get("lead_score"),
            "needs_editor": res.get("analysis", {}).get("needs_editor"),
            "language_version": res.get("analysis", {}).get("language_version"),
            "reason": res.get("analysis", {}).get("reason"),
            "evidence": "; ".join(res.get("analysis", {}).get("evidence", [])),
            "prospecting_message": res.get("analysis", {}).get("prospecting_message"),
            "red_flags": ";".join(res.get("analysis", {}).get("red_flags", []))
        })
    
    return output.getvalue()

# --- MAIN RUNNER FUNCTION (FOR STREAMLIT) ---
def run_prospector(niche, language, max_analyze, subs_min=0, subs_max=500000, api_key=None, logger=None):
    """
    Fonction principale appelée par Streamlit ou CLI.
    Retourne un dictionnaire avec {summary, rows, rejections, csv_content}
    """
    
    def log(msg):
        if logger:
            logger(msg)
        else:
            print(msg)

    log(f"🚀 Démarrage Prospector pour '{niche}' ({language})")
    
    client = get_groq_client(api_key)
    if not client:
        raise ValueError("Clé API Groq manquante")

    # 1. Recherche
    log(f"🔍 Recherche de candidats (target: {max_analyze})...")
    raw_videos = search_search_videos(niche, max_analyze * 3) # x3 pour marge
    log(f"   -> {len(raw_videos)} vidéos brutes trouvées.")

    analyzed_count = 0
    final_results = []
    rejections = []
    
    # 2. Analyse
    log("🧠 Analyse approfondie en cours...")
    
    for vid in raw_videos:
        if analyzed_count >= max_analyze:
            break
            
        details = get_video_details(vid['url'])
        if not details:
            continue
            
        # Filtre Date
        if not is_video_recent(details.get("upload_date"), days=30):
            d = format_date(details.get("upload_date", ""))
            rejections.append({"channel": details.get("channel", "Inconnu"), "reason": f"Trop vieux ({d})", "url": vid['url']})
            continue

        # Hard Gates
        is_allowed, reason, gates_flags = prequalify(details, subs_min, subs_max)
        if not is_allowed:
            rejections.append({"channel": details.get("channel", "Inconnu"), "reason": reason, "url": vid['url']})
            continue
            
        log(f"   Running AI on: {details.get('channel')}...")
        
        # AI Analysis
        analysis = analyze_candidate(details, language, client)
        analysis["red_flags"] = gates_flags + analysis.get("red_flags", [])
        
        # Adaptation pour Streamlit (mapping message options)
        analysis["message_option_1"] = analysis.get("prospecting_message")
        analysis["message_option_2"] = "Option alternative non générée par ce modèle."

        result_pkg = {
            "channel": details.get("channel"),
            "video_title": details.get("title"),
            "url": vid['url'],
            "upload_date": format_date(details.get("upload_date", "")),
            "subscriber_count": details.get("subscriber_count"),
            "view_count": details.get("view_count"),
            "analysis": analysis
        }
        
        final_results.append(result_pkg)
        analyzed_count += 1
        
        status = "✅" if analysis.get("needs_editor") else "❌"
        log(f"      {status} Score: {analysis.get('lead_score')} - {details.get('channel')}")

    # 3. Synthèse
    qualified = [r for r in final_results if r["analysis"].get("needs_editor")]
    
    summary = {
        "total_found": len(raw_videos),
        "analyzed": analyzed_count,
        "qualified": len(qualified)
    }
    
    csv_content = generate_csv_string(final_results, niche)
    
    log(f"🏁 Fini ! {len(qualified)} leads qualifiés trouvés.")
    
    return {
        "summary": summary,
        "rows": final_results,
        "rejections": rejections,
        "csv_content": csv_content
    }

# --- CLI WRAPPER ---
def main():
    print("\n" + "═" * 60)
    print("💎 GROQ YOUTUBE PROSPECTOR - CLI MODE")
    print("═" * 60)
    
    # Inputs simples pour CLI
    niche = input("🎯 Niche: ").strip()
    if not niche: return

    lang = input("🌍 Langue (fr/en) [fr]: ").strip() or "fr"
    
    try:
        max_v = int(input("🔢 Max analyse [5]: ").strip() or "5")
    except:
        max_v = 5
        
    # Lancement
    results = run_prospector(
        niche=niche, 
        language=lang, 
        max_analyze=max_v,
        subs_min=0,     # Default CLI
        subs_max=500000 # Default CLI
    )
    
    # Save CSV local
    if results["csv_content"]:
        with open("prospects_cli.csv", "w", encoding="utf-8") as f:
            f.write(results["csv_content"])
        print("\n💾 Saved to prospects_cli.csv")

if __name__ == "__main__":
    main()
