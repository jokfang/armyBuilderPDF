# `build_army_books_from_urls.py`

Ce script génère en lot des fichiers JSON et PDF à partir d'une liste d'URLs `army-info` d'Army Forge.

Pour chaque URL fournie, le script :

- télécharge les données de l'army book depuis l'API Army Forge
- convertit les données dans le format attendu par le générateur PDF
- applique les traductions de règles et de sorts
- écrit un fichier `.json`
- écrit un fichier `.pdf`

## Prérequis

- Python 3.11 ou plus récent recommandé
- accès réseau vers `army-forge.onepagerules.com`
- accès réseau vers la source du dictionnaire de traduction si tu utilises le dictionnaire par défaut

Selon ton environnement Python, certaines dépendances peuvent être nécessaires. Si une erreur mentionne `pypdf`, installe-le avec :

```powershell
python -m pip install pypdf
```

## Fichier d'entrée

Par défaut, le script lit le fichier :

```text
army-book-urls.txt
```

Le fichier doit contenir une URL `army-info` par ligne.

Les lignes vides sont ignorées.
Les lignes commençant par `#` sont traitées comme des commentaires.

Exemple :

```text
# Grimdark Future
https://army-forge.onepagerules.com/army-info/grimdark-future/some-book-uid

# Age of Fantasy
https://army-forge.onepagerules.com/army-info/age-of-fantasy/another-book-uid
```

## Utilisation rapide

Depuis la racine du projet :

```powershell
python .\build_army_books_from_urls.py
```

Cette commande utilise par défaut :

- `army-book-urls.txt` comme source
- `generated` comme dossier de sortie
- `fr` comme langue cible

## Syntaxe complète

```powershell
python .\build_army_books_from_urls.py [list_path] [--output-dir DOSSIER] [--language LANGUE] [--dictionary CHEMIN_OU_URL] [--print-friendly]
```

## Options

### `list_path`

Chemin optionnel vers un fichier texte contenant la liste des URLs.

Exemple :

```powershell
python .\build_army_books_from_urls.py .\mes-urls.txt
```

### `--output-dir`

Choisit le dossier dans lequel écrire les `.json` et `.pdf`.

Exemple :

```powershell
python .\build_army_books_from_urls.py --output-dir .\out
```

### `--language`

Langue cible des traductions.

Valeurs typiques :

- `fr` pour une sortie traduite en français
- `en` pour conserver le texte source autant que possible

Exemple :

```powershell
python .\build_army_books_from_urls.py --language en
```

### `--dictionary`

Permet de fournir une source de dictionnaire alternative.

Le paramètre accepte :

- un chemin local
- une URL HTTP ou HTTPS

Exemple avec un fichier local :

```powershell
python .\build_army_books_from_urls.py --dictionary .\common-rules.dictionary.ts
```

Exemple avec une URL :

```powershell
python .\build_army_books_from_urls.py --dictionary "https://example.com/common-rules.dictionary.ts"
```

### `--print-friendly`

Génère des PDF plus sobres, sans couleurs de faction ni séparateurs visuels par type d'unité.

Exemple :

```powershell
python .\build_army_books_from_urls.py --print-friendly
```

## Fichiers générés

Le script crée deux fichiers par army book dans le dossier de sortie :

- `*.json`
- `*.pdf`

Le nom du fichier est construit à partir :

- du code système
- du nom de faction normalisé
- de la version

Exemple :

```text
gff-battle-brothers-3-4-0.json
gff-battle-brothers-3-4-0.pdf
```

## Exemples

Génération standard :

```powershell
python .\build_army_books_from_urls.py
```

Utiliser un autre fichier d'URLs et un autre dossier de sortie :

```powershell
python .\build_army_books_from_urls.py .\lists\my-books.txt --output-dir .\exports
```

Génération en anglais :

```powershell
python .\build_army_books_from_urls.py --language en
```

Génération en français avec PDF print-friendly :

```powershell
python .\build_army_books_from_urls.py --language fr --print-friendly
```

## Génération de PDF depuis un dossier JSON

Le script [`generate_army_pdfs_from_dir.py`](./generate_army_pdfs_from_dir.py) permet de générer des PDF à partir de fichiers JSON déjà présents dans un dossier.

Il est utile si :

- tu as déjà généré les `.json`
- tu veux régénérer uniquement les PDF
- tu veux tester un rendu PDF sur un lot existant sans recontacter l'API Army Forge

### Utilisation recommandée dans ce repo

Si tes JSON ont été produits par `build_army_books_from_urls.py`, ils sont généralement dans `generated`.

Commande recommandée :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated
```

### Syntaxe complète

```powershell
python .\generate_army_pdfs_from_dir.py [input_dir] [--output-dir DOSSIER] [--print-friendly]
```

### Options

#### `input_dir`

Dossier contenant les fichiers `.json`.

Exemple :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated
```

#### `--output-dir`

Permet d'écrire les PDF dans un autre dossier que le dossier source.

Exemple :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated --output-dir .\pdf
```

#### `--print-friendly`

Génère des PDF plus sobres, sans couleurs de faction ni séparateurs visuels par type d'unité.

Exemple :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated --print-friendly
```

### Exemples d'usage

Régénérer tous les PDF à partir des JSON déjà créés :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated
```

Écrire les PDF dans un dossier séparé :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated --output-dir .\exports
```

Version print-friendly :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated --print-friendly
```

### Remarque importante

Le défaut interne actuel de `generate_army_pdfs_from_dir.py` est encore :

```text
ArmyForgeFR/src/data/generated
```

Dans ce repo, il est donc préférable de passer explicitement le dossier d'entrée, par exemple :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated
```

## Limitations connues

- Le script dépend de la disponibilité de l'API Army Forge.
- Le format exact des données renvoyées par Army Forge peut évoluer.
- Si le dictionnaire de traduction ne contient pas certaines entrées de faction, la génération continue mais certaines chaînes restent non traduites.

## Dépannage

### `FileNotFoundError` sur `army-book-urls.txt`

Le fichier de liste n'existe pas au chemin attendu.

Solutions :

- créer `army-book-urls.txt` à la racine du projet
- ou passer un chemin explicite :

```powershell
python .\build_army_books_from_urls.py .\mon-fichier.txt
```

### `Missing dependency: install pypdf`

Installe la dépendance :

```powershell
python -m pip install pypdf
```

### `Input directory not found` avec `generate_army_pdfs_from_dir.py`

Le dossier d'entrée passé au script n'existe pas.

Dans ce repo, utilise généralement :

```powershell
python .\generate_army_pdfs_from_dir.py .\generated
```

### `No JSON files found in directory`

Le dossier existe, mais ne contient pas de fichiers `.json`.

Vérifie :

- que `build_army_books_from_urls.py` a bien été exécuté avant
- que tu pointes vers le bon dossier
- que les fichiers générés ont bien l'extension `.json`

### Erreur réseau lors du chargement des données ou du dictionnaire

Vérifie :

- ta connexion réseau
- l'accès à `army-forge.onepagerules.com`
- l'accès à l'URL du dictionnaire

Tu peux aussi fournir un dictionnaire local avec `--dictionary`.

## Script concerné

Le script documenté ici est :

[`build_army_books_from_urls.py`](./build_army_books_from_urls.py)

Attention au nom : il s'agit bien de `urls` au pluriel.
