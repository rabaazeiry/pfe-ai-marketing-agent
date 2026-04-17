\# Sprint 12 — Intégration du scraping dans le produit



\## 🎯 Objectif

Connecter le système de scraping existant au backend Node.js et au frontend afin de pouvoir lancer un scraping depuis l’interface de l’application.



\---



\## 📌 Contexte

Le projet dispose déjà :

\- d’un backend Node.js

\- d’un service Python de scraping dans `backend/scraper`

\- d’une route Python `/v2/scrape`

\- d’une architecture de scraping intelligente

\- d’un premier scraping réel Instagram via HTTP

\- d’un frontend déjà fonctionnel



\---



\## ✅ Travail à réaliser



\### 1. Backend Node.js

Ajouter une route ou un service permettant de :

\- appeler le scraper Python (`/v2/scrape`)

\- recevoir la réponse

\- transmettre le résultat au frontend

\- préparer la persistance MongoDB si nécessaire



\### 2. Frontend

Ajouter dans l’interface un bouton ou une action permettant de :

\- lancer le scraping d’un projet ou d’un concurrent

\- afficher un état de chargement

\- afficher le résultat ou une erreur



\### 3. Flux produit complet

Mettre en place le flux suivant :

Frontend → Node backend → Python scraper → Node backend → UI



\---



\## 🚫 Contraintes

\- ne pas implémenter de nouvelle plateforme

\- ne pas ajouter Playwright

\- ne pas modifier profondément le scraping

\- utiliser uniquement l’implémentation Instagram HTTP existante

\- garder l’intégration simple et démontrable



\---



\## 📌 Résultat attendu

À la fin du sprint :

\- un scraping peut être lancé depuis l’interface

\- le backend Node appelle réellement le scraper Python

\- le frontend reçoit une réponse affichable

\- le système peut être démontré sur un projet réel

