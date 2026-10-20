# Référencement du site public ISBREE (Google)

Seul le **site public** (`web/isbree-public`, <https://isbree-public.onrender.com>) est préparé pour les moteurs de recherche. Le portail (Espace ISBREE) et l'API ne le sont pas : ils restent protégés par l'authentification et les permissions du serveur, et le portail interdit son indexation (`robots.txt` `Disallow: /`, en-tête `X-Robots-Tag: noindex`, balise `noindex`).

Préparer le site ne garantit pas son indexation : c'est Google qui décide, et seule la Search Console permet de la constater.

## Ce qui est en place

| Élément | Où | Détail |
|---|---|---|
| `robots.txt` | `src/app/robots.ts` | `Allow: /`, `Disallow: /images/` (fichiers d'images servis par le site), `Sitemap:` |
| `sitemap.xml` | `src/app/sitemap.ts` | pages fixes (accueil, À propos, Formations, Vie scolaire, Actualités, Galerie, Admissions, Préinscription, FAQ, Contact, /demonstration), pages d'information (mentions légales, confidentialité, conditions, règlement) et actualités publiées, avec leur vraie date de publication seulement |
| URL canonique | `src/lib/seo.ts` (`pageMetadata`) | une par page, relative à `ISBREE_PUBLIC_URL` (jamais le portail ni l'API, sans paramètre). Une page d'information dont le texte figure sur une page dédiée (À propos, Vie scolaire, Admissions) a pour canonique cette page dédiée, et n'est pas dans le sitemap |
| Titre et description | chaque `page.tsx` | propres à chaque page ; en mode démonstration, l'accueil et le gabarit indiquent qu'il s'agit d'une démonstration avec des données scolaires fictives |
| Open Graph | `src/lib/seo.ts`, `src/app/opengraph-image.tsx` | titre, description, URL et image de partage 1200 × 630 générée au build (logo ISBREE) |
| Vérification Google | `src/app/layout.tsx` | balise `google-site-verification` ajoutée **seulement** si `GOOGLE_SITE_VERIFICATION` est défini |
| 404 réels | `src/proxy.ts` | une actualité ou une page inconnue répond 404 dès la première visite |

Le contenu est rendu côté serveur (pages prérendues) : Google lit le texte sans exécuter de JavaScript. Le sitemap répond même si l'API est en veille : il contient alors au moins les pages fixes.

Le sitemap et les canoniques utilisent `ISBREE_PUBLIC_URL`. En ligne, il vaut `https://isbree-public.onrender.com` (variable du service `isbree-public` sur Render).

## Google Search Console (action manuelle)

Ces étapes demandent votre compte Google. Le code de vérification vient de Google : ne l'inventez pas, et ne le mettez pas dans le code.

1. Ouvrez <https://search.google.com/search-console> et choisissez **Ajouter une propriété**, type **Préfixe de l'URL** : `https://isbree-public.onrender.com/`.
2. Choisissez la méthode **Balise HTML**. Google affiche `<meta name="google-site-verification" content="…">` : copiez **uniquement** la valeur de `content`.
3. Dans Render, service **isbree-public** → **Environment**, ajoutez `GOOGLE_SITE_VERIFICATION` avec cette valeur.
4. Redéployez le site (**Manual Deploy → Deploy latest commit**) : les pages sont prérendues, la balise n'apparaît qu'après un nouveau build. Vérifiez-la :
   ```bash
   curl -s https://isbree-public.onrender.com/ | grep -o 'google-site-verification[^>]*'
   ```
5. Revenez dans la Search Console et cliquez sur **Valider**.
6. Menu **Sitemaps** : soumettez `https://isbree-public.onrender.com/sitemap.xml`.
7. Menu **Inspection de l'URL** : inspectez `https://isbree-public.onrender.com/`, puis **Demander une indexation**.

L'indexation prend en général de quelques jours à quelques semaines. L'hébergement gratuit peut répondre lentement après une veille : c'est sans conséquence pour l'exploration, Google réessaie.

## Vérifier

Tests automatiques (`npm run test:e2e` dans `web/isbree-public`, describe « search engines ») :

- `robots.txt` autorise les pages publiques et nomme le sitemap ;
- le sitemap est un `urlset` valide et ne contient ni le portail, ni l'API, ni `/images`, ni de doublon d'une page dédiée ; chaque page listée répond 200 ;
- chaque page a sa canonique, sa description propre, son image de partage, et `robots: index, follow`.

En ligne :

```bash
curl -s https://isbree-public.onrender.com/robots.txt
```

```bash
curl -s https://isbree-public.onrender.com/sitemap.xml
```

## Limites connues

- Domaine générique `onrender.com` : un nom de domaine propre aiderait le référencement ; il faudrait alors changer `ISBREE_PUBLIC_URL` et ajouter une nouvelle propriété Search Console.
- La démonstration présente des données fictives : la page `/demonstration` et le pied de page le disent, et cette transparence est volontairement conservée.
