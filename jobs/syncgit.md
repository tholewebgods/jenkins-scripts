
# sync-git

Script to create jobs for each remote branch matching a specific branch name pattern.

See the comment block in the script file for more details.

# Requirements

- dulwich (Git API) (https://pypi.python.org/pypi/dulwich)
- py-jenkins-cli (Jenkins CLI API) (https://github.com/tholewebgods/py-jenkins-cli)
- Mox 0.5.3 (https://code.google.com/p/pymox/) (only for unittests)
- Fudge 1.0.3 (http://farmdev.com/projects/fudge/) (only for unittests)

# Instructions

## Running

To run the `syncgit` one has to either install "py-jenkins-cli" to the `site-package` or export `PYTHONPATH` with the path to it.

## Tests

As with running the code "py-jenkins-cli" has to be present in the `PYTHONPATH`.

```
# Single run
python -m unittest syncgit_test

# Watch run
while inotifywait -e modify *.py; do python -m unittest syncgit_test ; done
```
