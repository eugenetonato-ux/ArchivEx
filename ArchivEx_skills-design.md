# ArchivEx — Design System (Public étudiant + Administration)

Ce document définit l'identité visuelle du projet. Contrairement à un outil interne, ArchivEx a **deux publics** : une plateforme publique/étudiante pensée pour convertir un visiteur en étudiant inscrit puis en Pass actif, et un espace administrateur pour la gestion académique et du contenu.

**Signature du produit** : Modern EdTech + SaaS premium + étudiant. Une identité sobre et rassurante, centrée sur la clarté du parcours École → Filière → Semestre → Matière → Épreuve, avec des points de verrouillage/déverrouillage visuellement explicites (🔒/🔓) qui rendent le modèle gratuit/Premium immédiatement compréhensible.

---

## 1. Palette de couleurs

Une palette cohérente et volontairement limitée.

| Rôle | Couleur (exemple) | Usage |
|---|---|---|
| Primaire | Indigo/violet | Actions principales, liens, navigation active |
| Secondaire | Bleu/turquoise | Accents, éléments interactifs secondaires |
| Fond | Très clair (proche blanc) | Fond général de l'application |
| Cartes | Blanc | Cartes filière, semestre, matière, épreuve |
| Texte | Bleu nuit | Titres, texte principal |
| Texte secondaire | Gris-bleu | Labels, méta-informations (année, type) |
| Succès | Vert | Gratuit, paiement confirmé, accès débloqué |
| Avertissement | Ambre | Accès partiel, information à nuancer |
| Verrouillage | Rouge/rose discret | Contenu Premium non débloqué |

Ne pas utiliser trop de couleurs ; éviter les gradients excessifs et les effets flashy.

---

## 2. Typographie

- **Corps de texte / interface** : *Inter* ou *Plus Jakarta Sans* — lisible, moderne, adapté à un usage intensif sur mobile.
- Hiérarchie typographique claire entre titres de section (École, Filière, Semestre), titres de carte (nom de matière/épreuve) et méta-informations (année, type, statut).

---

## 3. Composants — Espace public / étudiant

### 3.1 Page d'accueil (landing page)

- **Hero** : titre « Toutes tes anciennes épreuves. Au même endroit. », sous-titre expliquant la centralisation par filière/matière/semestre, deux boutons (« Trouver une épreuve », « Créer un compte »), illustration légère liée aux études/documents
- **Section « Comment ça marche »** : 4 étapes (Choisis ta filière → Choisis ton semestre → Trouve ta matière → Consulte ton épreuve)
- **Section statistiques** : nombre d'épreuves, de filières, de matières, d'étudiants — toujours des valeurs réelles, jamais inventées

### 3.2 Connexion / Inscription

- Connexion : carte centrale, email + mot de passe, actions (connexion, mot de passe oublié, inscription), beaucoup d'espace, logo, illustration légère, responsive
- Inscription : minimale (prénom, nom, email, mot de passe), puis sélection école/niveau/filière — rapide, sans friction

### 3.3 Page Filières

- Cartes filière avec icône, nom, courte description, nombre de matières, nombre d'épreuves si disponible, lien « Explorer → »

### 3.4 Page Semestres

- En-tête contextuel (ex. « PGP · L1 »)
- Cartes semestre : nombre de matières, nombre d'épreuves, badge d'accès (🔓 Accès complet si Pass actif, 🔒 Accès partiel sinon), lien « Explorer → »

### 3.5 Page Matières

- Liste des matières avec nombre d'épreuves et badge clair : ✓ Gratuit ou 🔒 Premium — visuellement faciles à distinguer au premier coup d'œil

### 3.6 Page Épreuves

- En-tête avec nom de la matière
- Barre de recherche + filtres (année, type, tri)
- Cartes épreuve : icône PDF, titre, année, type, matière, filière, statut, bouton « Voir → »
- Épreuve protégée : bloc de verrouillage explicite (« 🔒 Épreuve réservée — Débloquez le semestre pour accéder à toutes les épreuves ») avec bouton « Débloquer — [prix] »

### 3.7 Page Détail d'une épreuve

- Titre, informations (filière, niveau, semestre, année, type, date d'ajout)
- Actions : Voir le PDF, Télécharger, Ajouter aux favoris
- Si accès refusé : interface de verrouillage élégante, jamais un simple message d'erreur technique

### 3.8 Page Pass Semestre

- Titre « 🔓 Débloque ton semestre », sous-titre rassurant
- Carte produit claire : nom du Pass (école/niveau/filière/semestre), prix, liste des avantages (toutes les matières, toutes les épreuves, téléchargements autorisés, accès aux nouvelles épreuves)
- Bouton « 🔓 Débloquer maintenant », conditions affichées clairement, aucun dark pattern

### 3.9 Page Paiement

- Résumé du Pass concerné et du prix
- Moyens de paiement réellement disponibles (architecture prête pour un fournisseur futur ; mode simulé en développement)
- Confirmation post-paiement : « 🎉 Ton semestre est maintenant débloqué ! » + bouton « Explorer les épreuves »

### 3.10 Dashboard étudiant

- Message d'accueil (« Bonjour, [Prénom] 👋 »)
- Blocs : Ma filière, Mon semestre, Dernières épreuves, Mes favoris, Mon accès (état du Pass avec bouton « Débloquer le semestre » si non actif)

### 3.11 Page Favoris

- Titre « Mes épreuves favorites », cartes épreuve avec actions (consulter, télécharger si autorisé, retirer des favoris)
- Empty state : « Tu n'as encore aucune épreuve favorite. » + bouton « Explorer les épreuves »

### 3.12 Page Profil

- Nom, prénom, email, école, niveau, filière
- Section « Mes accès » listant les Pass actifs
- Édition des informations non sensibles uniquement

### 3.13 Navigation mobile

- Bottom navigation sur smartphone : Accueil | Recherche | Favoris | Profil

---

## 4. Composants — Espace administrateur

- Dashboard admin : nombre d'étudiants, de filières, de matières, d'épreuves, de Pass actifs, paiements récents — rester simple, pas de statistiques complexes dans le MVP
- Gestion académique : CRUD école/niveau/filière/année académique/semestre/matière
- Gestion des épreuves : ajout/modification/suppression, upload/remplacement de PDF, type, année, statut gratuit/Premium, publication/dépublication
- Gestion des étudiants : consultation utilisateur, filière, niveau, accès, désactivation de compte
- Gestion des Pass : Pass actifs/expirés, vérification d'accès, gestion manuelle exceptionnelle par l'administration
- Gestion des paiements : montant, statut, date, utilisateur, Pass concerné

---

## 5. Composants transverses

- **Boutons** : coins arrondis généreux, fond primaire plein pour l'action principale, contour discret pour les actions secondaires
- **Cartes** : coins arrondis, ombres légères, beaucoup d'espace blanc
- **Badges de statut** : pastille + texte court — `Gratuit` (vert/succès), `Premium` (verrouillage), `En attente`/`Réussi`/`Échoué`/`Annulé` pour les paiements
- **Modales, dropdowns, breadcrumbs** : cohérents avec la navigation académique en profondeur (École > Niveau > Filière > Semestre > Matière)
- **Progress indicators, skeleton loaders, empty states, toast notifications** : à prévoir pour les listes d'épreuves et le flux de paiement
- **Focus clavier** : toujours visible, accessibilité non négociable

À éviter : gradients excessifs, effets flashy, interfaces surchargées, animations inutiles.

---

## 6. Ton et contenu

- Ton simple, rassurant, orienté étudiant — pas de jargon technique dans les messages utilisateur
- Messages de confirmation positifs et explicites : « Ton semestre est maintenant débloqué ! », jamais de message d'erreur brut (« Erreur 500 », « NULL »)
- Messages d'erreur toujours actionnables : dire ce qui s'est passé et quoi faire ensuite
- Aucune pression artificielle ni dark pattern sur la page Pass Semestre — les conditions et le prix sont toujours affichés clairement avant l'action de paiement

---

## 7. Mobile-first

La majorité des utilisateurs utiliseront leur smartphone. Tester en priorité sur 360px, 390px, 430px (mobile), ~768px (tablette), 1280px/1440px (desktop) : accueil, connexion, inscription, sélection filière/semestre/matière, épreuves, détail épreuve, paiement, favoris, profil. Aucune page importante ne doit être inutilisable sur mobile.
