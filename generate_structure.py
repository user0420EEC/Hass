#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_structure.py
Автогенерация project_structure.json для репозитория Home Assistant / ESPHome / Zigbee2MQTT.

Что делает:
  - Рекурсивно обходит репозиторий (кроме игнорируемых каталогов).
  - Формирует список файлов и верхнеуровневую карту /root.
  - Индексирует YAML внутри includes/, esphome/, zigbee2mqtt/.
  - Пытается извлечь !include из YAML-файлов для построения relations.
  - Сохраняет результат в project_structure.json

Запуск:
  python generate_structure.py

Опциональные переменные окружения:
  REPO_URL   — URL репозитория (по умолчанию пусто).
  PROJECT_NAME — имя проекта (по умолчанию 'Home Assistant Configuration').
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# ---------------------- Настройки ---------------------- #
EXCLUDE_DIRS = {
    '.git', '.github', '.venv', 'venv', '__pycache__', '.mypy_cache',
    '.pytest_cache', '.idea', '.vscode', 'node_modules', '.cache', '.tox'
}
EXCLUDE_FILES_SUFFIXES = {
    '.pyc', '.pyo', '.log', '.tmp', '.swp', '.swo', '.bak', '~'
}
# ------------------------------------------------------ #

# эвристики описаний по названиям ключевых путей/файлов
DESCR_HINTS: Dict[str, str] = {
    'configuration.yaml': 'Главный файл конфигурации Home Assistant. Импортирует части через !include.',
    'customize.yaml': 'Кастомизация сущностей (friendly_name, иконки, атрибуты).',
    'scripts.yaml': 'Скрипты (service calls, последовательности, delay).',
    'scenes.yaml': 'Сцены (наборы состояний).',
    'blueprints': 'Шаблоны автоматизаций для HASS.',
    'custom_components': 'Кастомные интеграции HASS (Python, manifest.json).',
    'esphome': 'Конфигурации устройств ESPHome.',
    'includes': 'Подключаемые части конфигурации (sensors, switches и т.п.).',
    'zigbee2mqtt': 'Конфиги Zigbee2MQTT (broker, devices, groups).',
}

INCLUDE_RE = re.compile(r'!\s*include(?:_dir_(?:merge_list|merge_named|list|named))?\s+([^\s#]+)', re.IGNORECASE)

def is_excluded_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS

def is_excluded_file(path: Path) -> bool:
    if any(path.name.endswith(suf) for suf in EXCLUDE_FILES_SUFFIXES):
        return True
    return False

def node_type(p: Path) -> str:
    return 'directory' if p.is_dir() else 'file'

def describe(path: Path) -> str:
    base = path.name
    # точное совпадение
    if base in DESCR_HINTS:
        return DESCR_HINTS[base]
    # по вхождению
    for key, text in DESCR_HINTS.items():
        if key.lower() in str(path).lower():
            return text
    # общие типы
    s = base.lower()
    if s.endswith(('.yaml', '.yml')):
        return 'YAML конфигурация.'
    if s.endswith('.json'):
        return 'JSON конфигурация/данные.'
    if s.endswith('.py'):
        return 'Python модуль/скрипт.'
    if s.endswith('.sh'):
        return 'Shell-скрипт.'
    return ''

def list_all_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # фильтруем каталоги на месте, чтобы os.walk не заходил внутрь
        _dirnames = list(dirnames)
        for d in _dirnames:
            if is_excluded_dir(d):
                dirnames.remove(d)

        for fn in filenames:
            p = Path(dirpath) / fn
            if is_excluded_file(p):
                continue
            files.append(p)
    return sorted(files, key=lambda p: str(p).lower())

def top_level_entries(root: Path) -> List[Path]:
    return sorted([p for p in root.iterdir() if not is_excluded_dir(p.name)], key=lambda p: p.name.lower())

def build_root_map(entries: List[Path]) -> Dict[str, dict]:
    m: Dict[str, dict] = {}
    for e in entries:
        info = {'type': node_type(e)}
        desc = describe(e)
        if desc:
            info['description'] = desc
        m[e.name] = info
    return m

def yaml_includes_of(path: Path) -> List[str]:
    if not path.is_file():
        return []
    if path.suffix.lower() not in ('.yaml', '.yml'):
        return []
    try:
        txt = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []
    return sorted(set(m.group(1) for m in INCLUDE_RE.finditer(txt)))

def collect_yaml_includes(files: List[Path], root: Path) -> Dict[str, List[str]]:
    inc_map: Dict[str, List[str]] = {}
    for p in files:
        incs = yaml_includes_of(p)
        if incs:
            rel = str(p.relative_to(root)).replace('\\', '/')
            inc_map[rel] = incs
    return inc_map

def make_relations(include_map: Dict[str, List[str]]) -> Dict[str, List[str]]:
    # плоская карта зависимостей: файл -> список путей/паттернов, на которые он ссылается
    rel = {k: sorted(set(v)) for k, v in include_map.items()}
    return rel

def index_by_glob(root: Path) -> Dict[str, List[str]]:
    res: Dict[str, List[str]] = {}
    for d in ('includes', 'esphome', 'zigbee2mqtt', 'blueprints', 'custom_components'):
        dp = root / d
        if dp.exists() and dp.is_dir():
            res[d] = sorted([p.name for p in dp.iterdir() if p.is_file()], key=str.lower)
    return res

def main() -> int:
    root = Path('.').resolve()
    project_name = os.environ.get('PROJECT_NAME', 'Home Assistant Configuration')
    repo_url = os.environ.get('REPO_URL', '')

    files = list_all_files(root)
    tops = top_level_entries(root)
    includes_map = collect_yaml_includes(files, root)
    relations = make_relations(includes_map)
    index = index_by_glob(root)

    data = {
        'project_name': project_name,
        'repository': repo_url,
        'generated': datetime.now(timezone.utc).isoformat(),
        'root': build_root_map(tops),
        'files': [
            {
                'path': str(p.relative_to(root)).replace('\\', '/'),
                'type': node_type(p),
                **({'description': describe(p)} if describe(p) else {})
            } for p in files
        ],
        'files_index': index,
        'yaml_includes': includes_map,
        'relations': relations,
        'usage_rules': {
            'model_behavior': 'Использовать этот JSON как источник истины по структуре. Не выдумывать файлы/сущности вне карты.',
            'rules': [
                'ESPHome → /esphome/',
                'Zigbee → /zigbee2mqtt/',
                'Автоматизации → /blueprints/ и/или includes/automations.yaml',
                'Кастомизация → customize.yaml',
                'Главные настройки → configuration.yaml',
                'При ссылках на файлы указывать относительные пути'
            ]
        }
    }

    out = root / 'project_structure.json'
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('✓ project_structure.json создан/обновлён')
    return 0

if __name__ == '__main__':
    sys.exit(main())
