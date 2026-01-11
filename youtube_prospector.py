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
import os
import sys
import json
import csv
import time
import subprocess
from datetime import datetime, timedelta
from groq import Groq

# --- CONFIGURATION ---
GROQ_MODEL_ID = "llama-3.3-70b-versatile" 

def get_groq_client():
    """Configure et retourne le client Groq."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("❌ CRITIQUE : Variable GROQ_API_KEY manquante.")
        print("   Exportez-la : export GROQ_API_KEY='votre_clé'")
        sys.exit(1)
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

def prequalify(details: dict) -> tuple[bool, str, list]:
    """Hard gates pour disqualifier AVANT appel IA."""
    subs = details.get("subscriber_count")
    duration = details.get("duration", 0)
    channel = details.get("channel", "")

    red_flags = []
    
    # Règle 1: Gros Créateur
    if subs and subs >= 500000:
        return False, "Chaîne trop grosse (>500k)", ["too_big"]
        
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

# --- EXPORT ---
def save_to_csv(results: list, query: str):
    filename = "prospects.csv"
    file_exists = os.path.isfile(filename)
    
    fieldnames = [
        "run_timestamp", "niche", "query_used", "channel", 
        "video_title", "video_url", "upload_date", "subscriber_count", 
        "view_count", "lead_score", "needs_editor", 
        "language_version", "reason", "evidence", "prospecting_message", "red_flags"
    ]
    
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
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
    print(f"\n💾 Données sauvegardées dans '{filename}'")

# --- MAIN LOOP ---
def main():
    print("\n" + "═" * 60)
    print("💎 GROQ YOUTUBE PROSPECTOR - V1.0 (STRICT MODE)")
    print("═" * 60)
    
    client = get_groq_client()
    
    # 1. Inputs Utilisateur
    niche = input("🎯 Niche (ex: Fitness, Immo, Crypto): ").strip()
    if not niche: 
        print("❌ Niche requise."); return

    lang_choice = input("🌍 Version (fr/en) [fr]: ").strip().lower() or "fr"
    if lang_choice not in ["fr", "en"]: lang_choice = "fr"
    
    try:
        max_analyze = int(input("🔢 Nb max à analyser [10]: ").strip() or "10")
    except:
        max_analyze = 10
        
    export_csv = input("💾 Exporter CSV? (o/n) [o]: ").strip().lower() or "o"

    # 2. Recherche
    print(f"\n🔍 Recherche 'strict 30 jours' pour: {niche}...")
    # On cherche large (x3) pour avoir du rab après filtrage
    raw_videos = search_search_videos(niche, max_analyze * 3)
    
    print(f"   -> {len(raw_videos)} vidéos brutes trouvées.")
    
    # 3. Filtrage & Analyse
    analyzed_count = 0
    final_results = []
    
    print("\n🚀 Démarrage de l'analyse approfondie...")
    start_time = time.time()
    
    for vid in raw_videos:
        if analyzed_count >= max_analyze:
            break
            
        # Get details
        print(f"   ⏳ Récupération data: {vid['title'][:40]}...")
        details = get_video_details(vid['url'])
        
        if not details: 
            print("      ⏭️  Skip (data error)")
            continue
            
        # Filtre Date Strict (30 jours)
        if not is_video_recent(details.get("upload_date"), days=30):
            d = format_date(details.get("upload_date", ""))
            print(f"      🗑️  Rejet: Trop vieux ({d})")
            continue
            
        # HARD GATES / PREQUALIFICATION
        is_allowed, reason, gates_flags = prequalify(details)
        if not is_allowed:
            print(f"      ⛔ DISQUALIFIÉ (Hard Gate): {reason}")
            continue

        # Analyse IA
        print("      🧠 Analyse Groq en cours...")
        analysis = analyze_candidate(details, lang_choice, client)
        
        # Merge red flags
        analysis["red_flags"] = gates_flags + analysis.get("red_flags", [])
        
        # Stockage
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
        
        # Affichage temps réel
        score = analysis.get("lead_score", 0)
        status = "✅ QUALIFIÉ" if analysis.get("needs_editor") else "❌ REJETÉ"
        print(f"      🎯 Score: {score}/100 | {status}")
        if analysis.get("needs_editor"):
            print(f"         💡 {analysis.get('reason')}")
        print("")

    # 4. Synthèse
    duration = time.time() - start_time
    qualified = [r for r in final_results if r["analysis"].get("needs_editor")]
    
    print("\n" + "═" * 60)
    print(f"🏁 TERMINÉ en {duration:.1f}s")
    print(f"📊 Analysés: {len(final_results)} | Qualifiés: {len(qualified)}")
    print("═" * 60)
    
    for q in qualified:
        a = q["analysis"]
        print(f"\n🏆 LEAD: {q['channel']}")
        print(f"   📺 Vidéo: {q['video_title']}")
        print(f"   📈 Abonnés: {q.get('subscriber_count', 'N/A')}")
        print(f"   🔍 Preuves: {', '.join(a.get('evidence', []))}")
        print(f"   ✉️  Message ({lang_choice}):")
        print(f"   \"{a.get('prospecting_message')}\"")
        
    if export_csv == "o" and final_results:
        save_to_csv(final_results, niche)

if __name__ == "__main__":
    main()
