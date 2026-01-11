# 💎 YouTube Prospector Pro

Outil de prospection automatisé pour trouver des clients YouTube (montage vidéo).

## 🚀 Installation & Lancement (Windows/Mac/Linux)

### 1. Installer les dépendances
Ouvrez un terminal dans ce dossier et lancez :
```bash
pip install -r requirements.txt
```

### 2. Configurer la Clé API Groq
Vous avez deux options :
- **Option A (Permanente)** : Créez une variable d'environnement nommée `GROQ_API_KEY`.
  - *Windows (PowerShell)* : `$env:GROQ_API_KEY="votre_cle_ici"`
  - *Mac/Linux* : `export GROQ_API_KEY="votre_cle_ici"`
- **Option B (Session)** : Vous pourrez entrer la clé directement dans l'interface de l'application.

### 3. Lancer l'Application
```bash
streamlit run streamlit_app.py
```

Une fenêtre de navigateur s'ouvrira automatiquement.

---

**Note** : Le fichier `prospects.csv` sera généré dans le dossier courant ou proposé en téléchargement.
