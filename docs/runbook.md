# Runbook — exploitation locale / LAN

## Démarrer / arrêter

```bash
docker compose up -d --build     # démarre db, redis, web (migrations appliquées au démarrage)
docker compose logs -f web       # suivre les logs de l'API
docker compose down              # arrêter (les données restent dans les volumes)
```

`docker compose down -v` **supprime les volumes, donc toute la base**. À n'utiliser que sur un poste de développement.

## Vérifier que l'API répond

```bash
curl http://localhost:8000/api/v1/health/
```

Depuis un téléphone sur le même Wi-Fi : remplacer `localhost` par l'IP du serveur et ajouter cette IP à `DJANGO_ALLOWED_HOSTS` dans `.env`.

## Premier démarrage d'un établissement

```bash
docker compose exec web python manage.py bootstrap_school --help
```

Le mot de passe est demandé de façon interactive (jamais en argument, pour ne pas finir dans l'historique du shell).

## Tests et qualité

```bash
docker compose run --rm web pytest                 # tests
docker compose run --rm web pytest --create-db     # après une modification de migration
docker compose run --rm web ruff check .           # lint
docker compose run --rm web ruff format .          # formatage
```

## Migrations

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

## Sauvegarde de la base

```bash
docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backup.sql
```

## Points d'attention Windows

- Utiliser `py` et non `python` (ce dernier ouvre le Microsoft Store).
- PowerShell 5.1 écrit les fichiers UTF-8 **avec BOM** : éditer `.env` avec un éditeur de code, pas avec `Set-Content`.

## Extension PostgreSQL `btree_gist`

La migration `academics.0001` exécute `CREATE EXTENSION btree_gist`. Cette extension est nécessaire aux contraintes interdisant le chevauchement des années et des périodes (ADR 0008). Le superutilisateur Docker en a le droit. Si la base de production utilise un rôle sans ce privilège, créez l'extension une fois en tant qu'administrateur, avant `migrate` :

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS btree_gist"'
```

## Base de test (`db_test`)

La suite pytest n'utilise **jamais** la base de développement. `pyproject.toml` force `--ds=config.settings.test`, qui pointe vers le service `db_test` :
- même PostgreSQL 17 que `db` ;
- données en RAM (`tmpfs`) et `fsync` désactivé : elles disparaissent à l'arrêt du conteneur ;
- un test-garde (`test_suite_runs_on_the_test_settings_and_database`) échoue si la suite tourne sur d'autres settings ou une autre base.

Les mots de passe y sont hachés en Argon2 avec un coût minimal (tests uniquement).

```bash
docker compose run --rm web pytest              # ~2 min
docker compose run --rm web pytest --create-db  # après une nouvelle migration
```
