
# sync-git

Script to create jobs for each remote branch matching a specific branch name pattern.

See the comment block in the script file for more details.

# Requirements

- Python 2.6 or 2.7
- argparse (only if using Python 2.6)
- dulwich (Git API) (https://pypi.python.org/pypi/dulwich)
- py-jenkins-cli (Jenkins CLI API) (https://github.com/tholewebgods/py-jenkins-cli)
- Mox 0.5.3 (https://code.google.com/p/pymox/) (only for unittests)
- Fudge 1.0.3 (http://farmdev.com/projects/fudge/) (only for unittests)

# Instructions

## Running

To run the `syncgit` one has to either install "py-jenkins-cli" to the `site-package` or export `PYTHONPATH` with the path to it.

```
python /path/to/syncgit.py --host http://localhost:8080/ --key /var/lib/jenkins/.ssh/id_rsa_local_jenkins_key --jar /tmp/jenkins-cli.jar --tpl-job 'TEMPLATE Build ACME' --job-name-tpl 'Build ACME %s' --git-repo . --ref-regex '^refs/remotes/origin/(dev|bugfix)/ACME-[0-9]+' --max-commit-age 30
```

## Tests

As with running the code "py-jenkins-cli" has to be present in the `PYTHONPATH`.

```
# Single run
python -m unittest syncgit_test

# Watch run
while inotifywait -e modify *.py; do python -m unittest syncgit_test ; done
```
