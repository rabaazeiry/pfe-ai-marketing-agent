\# 🧠 Sprint 10 — Scraping Intelligent (Architecture)



\## 🎯 Objectif



Mettre en place une architecture de scraping intelligente intégrée au backend existant.



\---



\## 📌 Contexte



Le projet Battouta possède déjà :



\* Backend Node.js

\* MongoDB local

\* Modèles existants :



&#x20; \* Project

&#x20; \* Competitor

&#x20; \* SocialAnalysis

&#x20; \* Insight

&#x20; \* Report



👉 Le scraping doit alimenter ces modèles.



\---



\## ⚙️ Méthodes de scraping



1\. API (prioritaire)

2\. HTTP interception

3\. Brute force (fallback)



\---



\## 🧠 Nœud intelligent



Créer un système qui :



\* choisit la meilleure méthode

\* priorité : API → HTTP → brute force

\* évite les doublons

\* nettoie les données

\* normalise les formats



\---



\## 🔄 Pipeline



Scraping → Nettoyage → Normalisation → Injection MongoDB



\---



\## 📂 Architecture attendue



\* services scraping

\* orchestrateur intelligent

\* mapping vers modèles existants

\* structure modulaire



\---



\## 🚫 Contraintes



\* ne pas recréer des modèles inutiles

\* utiliser MongoDB local

\* ne pas implémenter scraping complet (juste structure)



\---



\## 📌 Résultat attendu



\* architecture propre

\* code skeleton

\* prêt pour Sprint 11 (implémentation)



