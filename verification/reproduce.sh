#!/usr/bin/env bash
# ПОВТОРИ ГИ ПРОВЕРКИТЕ
#
# Една команда. Ги извршува сите проверки што не бараат жива работна површина и
# печати пресуда по секоја. Ништо овде не поднесува цел кон ARIES, не стартува
# сервис и не пишува во var/aries.db — базата се отвора само за читање.
#
#     ./verification/reproduce.sh
#
# Излез нула значи дека сè поминало. Секој ред носи што се тврди и каде е суровиот
# артефакт, за да тврдењето може да се провери и без да се верува на овој испис.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH="$ROOT/vendor/agentic-core:$ROOT/vendor:$ROOT"
D=experiments/product/independent-acceptance

pass=0; fail=0; skip=0
rule() { printf '%s\n' "────────────────────────────────────────────────────────────────────────"; }
# Проверка што бара дневник не може да работи на свеж клон: базата носи вистинска
# работа на корисникот и не се објавува. Отсуството на податок не е неуспех на
# системот, па таа проверка СЕ ПРЕСКОКНУВА со наведена причина наместо да падне.
needs_ledger() { [ -f var/aries.db ]; }

step() {
  local what="$1"; shift
  rule
  printf '▸ %s\n' "$what"
  printf '  команда: %s\n\n' "$*"
  if "$@"; then printf '\n  ПРЕСУДА: ПОМИНА\n'; pass=$((pass+1))
  else printf '\n  ПРЕСУДА: ПАДНА\n'; fail=$((fail+1)); fi
}

printf 'ARIES — повторување на проверките\n'
printf 'време   : %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'commit  : %s\n' "$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
printf 'машина  : %s · %s\n' "$(uname -sr)" "$(lsb_release -ds 2>/dev/null || echo '?')"
printf 'python  : %s\n' "$($PY --version 2>&1)"

step "Опсези: единаесет обиди за бегство мора да бидат одбиени" \
     "$PY" $D/test_scopes_adversarial.py
step "Буџети: дваесет истовремени резервации наспроти таван од пет" \
     "$PY" $D/test_budgets_concurrent.py
step "Потекло на контекст: внесена инструкција мора да ја задржи етикетата" \
     "$PY" $D/test_context_provenance.py
step "Чувар против повторување: мутирачки чекор по истек на време" \
     "$PY" $D/test_replay_guard.py
step "Оракулите на фикстурата: може ли воопшто да паднат" \
     "$PY" $D/validate_oracles.py
if needs_ledger; then
  step "Верификациски бројки врз ЦЕЛИОТ дневник, не врз примерок" \
       "$PY" $D/verification_truth.py
else
  rule
  printf '▸ %s\n' "Верификациски бројки врз целиот дневник"
  printf '\n  ПРЕСКОКНАТО: нема var/aries.db. Дневникот носи вистинска работа на\n'
  printf '  корисникот и не се објавува. Бројките што документите ги цитираат се\n'
  printf '  во verification/ledger_frozen.json, снимени од таа база.\n'
  skip=$((skip+1))
fi
step "Пребројувања од живите објекти, не од текстуален шаблон" \
     "$PY" $D/repo_facts.py

rule
printf 'ПОМИНАА %d · ПАДНАА %d · ПРЕСКОКНАТИ %d\n' "$pass" "$fail" "$skip"
rule
printf 'Суровите резултати се во %s/raw/\n' "$D"
printf 'Снимокот што документите го цитираат е verification/ledger_frozen.json\n'
exit $(( fail > 0 ))
