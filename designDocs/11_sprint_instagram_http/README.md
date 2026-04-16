\# Sprint 11 — Instagram HTTP Scraping



\## 🎯 Objectif

Implémenter la première version réelle du scraping sur Instagram en utilisant uniquement la méthode HTTP.



\---



\## 📌 Contexte

Le Sprint 10 a mis en place l’architecture de scraping intelligente :

\- orchestrateur

\- cleaner

\- normalizer

\- dedupe

\- methods

\- mappers

\- route /v2/scrape



Cette architecture est prête, mais les méthodes sont encore des stubs.



\---



\## 🧩 Portée du sprint

Ce sprint se limite à :



\- plateforme : Instagram

\- méthode : HTTP

\- extraction simple et minimale



\---



\## ✅ Ce qui doit être fait



\### 1. Implémenter `http\_method.py`

\- récupérer une cible Instagram publique

\- faire une requête HTTP simple

\- extraire un minimum de données exploitables

\- retourner des `RawPost`



\### 2. Connecter la méthode HTTP à l’orchestrateur

\- vérifier que l’orchestrateur peut utiliser `http\_method`



\### 3. Vérifier le pipeline complet

\- HTTP → cleaner → normalizer → dedupe → mapper



\### 4. Tester `/v2/scrape`

\- envoyer une requête de test

\- vérifier la réponse JSON



\---



\## 🚫 Ce qui ne doit pas être fait

\- pas de brute force

\- pas de Playwright

\- pas d’autres plateformes

\- pas de scraping massif

\- pas de logique trop complexe



\---



\## 📌 Résultat attendu

À la fin du sprint :

\- le système retourne une réponse réelle sur un cas Instagram

\- le pipeline complet fonctionne

\- l’architecture du Sprint 10 est validée en pratique



\---



\## 🚀 Étape suivante

Ajouter le fallback browser / brute force si HTTP échoue

