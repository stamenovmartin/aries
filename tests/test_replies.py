"""What ARIES says about an outcome, and what it must never say.

The bug this guards, measured on 2026-09-30: the voice loop worked end to end —
"Ари, колку место има на дискот" heard correctly, wake gate passed, `system.storage`
executed, step `state=verified` — and then ARIES said out loud:

    "Task queued."

while the result already held `disk.used_pct 8.5%` and `free_gib 396.28`. Every
layer worked and none of it reached the person in words. That is what "не гледам
интелигентен Linux" meant, and it was a fair verdict.

So these checks are about articulation, not about capability. The process words are
pinned as a **blocklist with real examples**, because each one was actually spoken
or actually written into a summary that would have been spoken.

No audio is played here. `sentence()` is pure text.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-replies')
from aries.speech import replies

# The shape of a real `system.storage` result, trimmed from the goal that said
# "Task queued". The duplication is real: the executor's copy and the verifier's
# independent re-read are both in the record, which is the point of the verifier.
DISK = {
    "state": "partial",
    "steps": [{"capability": "system.storage", "state": "verified",
               "result": {"summary": "Independently verified",
                          "execution_result": {"probe": "statvfs", "filesystems": [
                              {"metric": "disk.used_pct", "subject": "/", "value": 8.5, "unit": "%",
                               "detail": {"free_gib": 396.28, "size_gib": 433.09,
                                          "fstype": "ext4", "device": "/dev/sdc1"}},
                              {"metric": "disk.used_pct", "subject": "/boot/efi", "value": 0.6, "unit": "%",
                               "detail": {"free_gib": 0.5, "size_gib": 0.5}}]},
                          "verification": {"met": True, "filesystems": [
                              {"metric": "disk.used_pct", "subject": "/", "value": 8.5, "unit": "%",
                               "detail": {"free_gib": 396.28, "size_gib": 433.09}}]}}}],
}


async def test_the_answer_carries_the_measurement_not_the_process():
    for language, wanted in (("mk", ("8.5", "396", "433")), ("en", ("8.5", "396", "433"))):
        said = replies.sentence(DISK, language=language)
        for token in wanted:
            check(f'[{language}] the answer contains {token}: {said}', token in said)
        check(f'[{language}] it does not say "Task queued"', "queued" not in said.casefold())
        check(f'[{language}] it does not say "Independently verified"',
              "independently" not in said.casefold())


async def test_a_mount_point_nobody_asked_about_is_not_read_aloud():
    """`/boot/efi` is 500 MB of firmware, always nearly empty, and reading it out
    makes the answer longer without making it more useful."""
    said = replies.sentence(DISK, language="mk")
    check('/boot/efi is left out: ' + said, "boot" not in said)
    check('the root filesystem is not read out as a slash', " / " not in said)


async def test_the_same_measurement_is_not_said_twice():
    """The verifier's independent re-read is in the record on purpose. Saying the
    number twice would turn that integrity feature into a stutter."""
    said = replies.sentence(DISK, language="mk")
    check('8.5 appears once: ' + said, said.count("8.5") == 1)


async def test_process_language_is_never_spoken():
    for summary in ("Task queued", "Independently verified", "1 results", "3 cards",
                    "accepted", "unconfirmed", ""):
        said = replies.sentence({"state": "done", "summary": summary}, language="mk")
        # An empty summary has nothing to leak, so the substring check is only
        # meaningful for the process words themselves.
        leaked = bool(summary) and summary.casefold() in said.casefold()
        check(f'{summary!r} becomes a plain answer, not itself: {said}',
              said == "Готово." and not leaked)


async def test_a_real_summary_written_for_a_person_is_kept():
    """The blocklist must not eat good summaries — most capabilities write one."""
    for summary in ("Playing Bohemian Rhapsody", "Volume 0.30 to 0.40",
                    "8 networks visible, 1 already saved"):
        said = replies.sentence({"state": "done", "summary": summary}, language="mk")
        check(f'kept: {said}', summary in said)


async def test_states_a_person_needs_to_hear_about():
    check('waiting for approval is said plainly',
          "одобрување" in replies.sentence({"state": "proposed"}, language="mk"))
    failed = replies.sentence({"state": "failed", "error": "нема мрежа"}, language="mk")
    check('a failure says it failed and why: ' + failed,
          "Не успеа" in failed and "нема мрежа" in failed)
    check('an empty outcome is not silence', replies.sentence({}, language="mk"))
    check('a non-dict outcome is not a crash', replies.sentence(None, language="en"))


async def test_a_failed_goal_never_speaks_its_stale_measurements():
    """Found by the Codex session reviewing this module on 2026-09-30, not by me.

    An earlier step's readings survive in the record, so mining measurements
    before checking the state made a FAILED goal say "Дискот е на 8.5%" and never
    mention the failure. Confidently speaking stale evidence is the precise thing
    the rest of this project refuses to do, and it was in the module written to
    fix exactly that class of dishonesty.
    """
    stale = {"state": "failed", "error": "мрежата падна", "steps": [{"result": {
        "execution_result": {"filesystems": [
            {"metric": "disk.used_pct", "subject": "/", "value": 8.5, "unit": "%",
             "detail": {"free_gib": 396.28, "size_gib": 433.09}}]}}}]}
    said = replies.sentence(stale, language="mk")
    check('it says it failed: ' + said, "Не успеа" in said)
    check('it gives the reason', "мрежата падна" in said)
    check('it does NOT speak the stale measurement', "8.5" not in said and "396" not in said)
    for state in ("failed", "refused", "interrupted", "error"):
        spoken = replies.sentence({**stale, "state": state}, language="en")
        check(f'{state} reports failure, not readings: {spoken}',
              "failed" in spoken.casefold() and "8.5" not in spoken)
    # A process word is not a reason a person can use.
    check('a process word is not offered as the reason',
          replies.sentence({"state": "failed", "summary": "Task queued"}, language="mk") == "Не успеа.")
    # And the same readings under a good state are still spoken.
    fine = replies.sentence({**stale, "state": "done", "error": None}, language="mk")
    check('a done goal still speaks the measurement: ' + fine, "8.5" in fine)


async def test_readings_are_found_wherever_they_sit():
    """Shape-driven, not path-driven: a capability that nests its output somewhere
    new is still heard, which is what keeps this file from needing an entry per
    capability."""
    buried = {"state": "done", "a": {"b": [{"c": {
        "metric": "cpu.temperature", "subject": "package", "value": 61.0, "unit": "C"}}]}}
    said = replies.sentence(buried, language="mk")
    check('a deeply nested reading is still spoken: ' + said, "61" in said)
    check('a trailing .0 is not read aloud', "61.0" not in said)


async def test_the_answer_is_a_sentence_not_a_report():
    """Three facts is an answer; ten is a lecture nobody listens to."""
    many = {"state": "done", "readings": [
        {"metric": f"disk.used_pct", "subject": f"/m{i}", "value": i, "unit": "%"} for i in range(1, 12)]}
    said = replies.sentence(many, language="mk")
    check(f'bounded to a few facts ({said.count(".")} sentences)', said.count(".") <= 4)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
