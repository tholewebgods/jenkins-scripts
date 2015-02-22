import json
import re
import datetime
import time
import os
import os.path
import dulwich.repo
import jenkinscli
import xml.etree.ElementTree as ET
import sys
import argparse
import textwrap

# This script will create jobs for each remote branch found in the repository
# in the current directory. It will also remove the jobs if the branches are
# no longer exiting.
#
# - The branch name pattern can be configured
# - The template job name can be configured
# - The branch name placeholder in the template job can be configured
# - A branch is being ignored if the last commit is older than a configurable
#   amount of days
#
# Requirements:
# - Python 2.6 (2.7 should work too)
# - dulwich (install it using # pip install dulwich)
# - py-jenkins-cli (https://github.com/tholewebgods/py-jenkins-cli)
#

BINARY_NAME="syncgit"
VERSION="0.1"

# Default for max. commit age of a branch
DEFAULT_MAX_COMMIT_AGE=30


class Jenkins(object):

	"""
		Jenkins job management.

		- job_tpl -- the exact job name used as a template (this job might/should be disabled)
		- branch_name_placeholder -- the string within the job template that will be replaced with the branch name
		- job_name_tpl -- the resulting job name, has to contain one "%s" placeholder that will be replaced with the sanitized branch name
	"""
	def __init__(self, host, cli_jar, ssh_key, job_tpl, branch_name_placeholder, job_name_tpl):
		self._jenkins = jenkinscli.JenkinsCli(host, cli_jar, ssh_key)

		self._job_template = job_tpl
		self._branch_name_placeholder = branch_name_placeholder
		self._job_name_tpl = job_name_tpl


	"""
	Create Job for Git ref name
	"""
	def create_job(self, ref_name):
		# load template and replace placeholder in config
		config_template = self._jenkins.get_job(self._job_template)
		config = config_template.replace(self._branch_name_placeholder, ref_name)

		# replace slashes in ref name to  get clean job name and build job name
		filtered_ref_name = ref_name.replace("origin/", "")
		# Python 2.6 does not support flags=..., using (?i)
		filtered_ref_name = re.sub("(?i)[^a-z0-9_-]+", "-", filtered_ref_name)
		job_name = self._job_name_tpl % filtered_ref_name

		print "Creating and enabling job '%s' for branch %s" % (job_name, ref_name)
		self._jenkins.create_job(job_name, config)
		self._jenkins.enable_job(job_name)

	"""
	Remove Job by Git ref name
	"""
	def remove_job(self, ref_name):
		# replace slashes in ref name to  get clean job name and build job name
		filtered_ref_name = ref_name.replace("origin/", "")
		# Python 2.6 does not support flags=..., using (?i)
		filtered_ref_name = re.sub("(?i)[^a-z0-9_-]+", "-", filtered_ref_name)
		job_name = self._job_name_tpl % filtered_ref_name

		print "Removing job '%s' for branch '%s'" % (job_name, ref_name)
		self._jenkins.delete_job(job_name)

	# get branch from one Job's config
	def _get_branch_from_config(self, config):
		root = ET.fromstring(config)

		name_element = root.findall(".//scm/branches/hudson.plugins.git.BranchSpec/name")

		if len(name_element) == 1:
			return name_element[0].text
		else:
			return None

	"""
	Get all branches that are configured by Jobs.
	Examines each Job in the list for their branch names
	"""
	def get_currently_configured_branches(self):
		jobs = self._jenkins.get_joblist()

		branches = []

		for job in jobs:
			if re.match("^" + (self._job_name_tpl % ""), job):
	                        config = self._jenkins.get_job(job)
	                        branch_name = self._get_branch_from_config(config)

				if not re.match("^refs/remotes/", branch_name):
					branch_name = "refs/remotes/" + branch_name

				branches.append(branch_name)

		return branches

"""
Represents branches in Git
"""
class GitBranches(object):

	"""
		Git branch management.

		repo -- Repository location (relative or absolute paths)
		ref_matcher -- A regular expression that matches branch names to create jobs for
		max_commit_age -- Max days the last commit was made to a branch
	"""
	def __init__(self, repo, ref_matcher, max_commit_age):
		self._repo = dulwich.repo.Repo(repo)
		self._ref_matcher = ref_matcher
		self._max_commit_age = max_commit_age

	def get_branches(self):
		_refs = []

		# iterate over branches (refs) and their SHA1
		for ref, sha1 in self._repo.get_refs().iteritems():
			# ref matches the configured matcher
			if re.match(self._ref_matcher, ref):
				obj = self._repo.get_object(sha1)
				_refs.append([ref, sha1, obj.commit_time])

		# filter (ref, SHA1, commit time) tupel for outdated branches
		refs = filter(lambda x: self._within_days(x[2], self._max_commit_age), _refs)

		# extract ref
		refs = set([x[0] for x in refs])

		return refs

	# Return True if the Unix timestamp is within the timerange now - days
	def _within_days(self, timestamp, days):
		return datetime.datetime.fromtimestamp(timestamp) >= (datetime.datetime.now() + datetime.timedelta(days=-days))


class GitJenkinsSync(object):

	def __init__(self, host, cli_jar, ssh_key, job_tpl, branch_name_placeholder, job_name_tpl, repo, ref_matcher, max_commit_age):
		self._jenkins = Jenkins(host, cli_jar, ssh_key, job_tpl, branch_name_placeholder, job_name_tpl)
		self._git = GitBranches(repo, ref_matcher, max_commit_age)

	"""Do the actual sync. Query both sides, do diff/intersection and create/remove jobs"""
	def sync(self):
		git_branches = self._git.get_branches()
		job_branches = set(self._jenkins.get_currently_configured_branches())

		print "Found these branches in the repository:\n  %s" % "\n  ".join(git_branches)
		print "Found these branches configured in Jenkins:\n  %s" % "\n  ".join(job_branches)

		to_remove = job_branches - git_branches

		if len(to_remove) > 0:
			print "Remove these:\n  %s" % "\n  ".join(to_remove)

			for ref in to_remove:
				self._jenkins.remove_job(ref.replace("refs/remotes/", ""))
		else:
			print "No branch jobs to remove."


		to_create = git_branches - job_branches

		if len(to_create) > 0:
			print "Create these:\n  %s" % "\n  ".join(to_create)

			for ref in to_create:
				self._jenkins.create_job(ref.replace("refs/remotes/", ""))
		else:
			print "No branch jobs to create."

class CustomParser(argparse.ArgumentParser):

	# extend help screen to print more
	def print_help(self):
		super(CustomParser, self).print_help()
		print "example usage:"
		print """
Create a job named "Build Project XYZ TEMPLATE" and set "BBBBB" in the Git
config section for the branch name.

  %s --host http://localhost:8080/ --key /home/jenkins/.ssh/id_rsa_local \\
   --jar /tmp/jenkins_cli.jar --tpl-job "Build Project XYZ TEMPLATE" \\
   --job-name-tpl "Build Project XYZ %%s" --branch-placeholder "BBBBB" \\
   --ref-regex "^refs/remotes/origin/((dev|bugfix)/ACME-[0-9]+|int/[0-9]+)" \\
   --git-repo /tmp/sync-checkout --max-commit-age 14

This will create jobs named like "Build Project XYZ dev-ACME-123-name"
		""" % (BINARY_NAME)


# Validating store action for --max-commit-age
class MaxAgeSwitchAction(argparse.Action):
	def __call__(self, parser, namespace, values, option_string=None):
		if values > 1000 or values < 1:
			raise Exception("Max commit age %d exceeds 1 - 1000" % values)

		setattr(namespace, self.dest, values)

# Internal exception
class ArgumentValidationException(Exception):

	def __init__(self, msg):
		super(ArgumentValidationException, self).__init__(msg)

def _validate_arguments(parsed):
	if not os.path.exists(parsed.ssh_key):
		raise ArgumentValidationException("SSH Key does not exist: " + parsed.ssh_key)

	if not os.path.exists(parsed.jar):
		raise ArgumentValidationException("Jenkins CLI .jar does not exist: " + parsed.jar)

	if parsed.jobname_tpl.count("%s") != 1:
		raise ArgumentValidationException("Expected one \"%s\" placeholder in the job name template.")

	if not os.path.exists(parsed.git_repo_path):
		raise ArgumentValidationException("Git directory does not exist: " + parsed.git_repo_path)

	try:
		re.match(parsed.ref_regex, "")
	except Exception as e:
		raise ArgumentValidationException("Malformed regular expression '" + parsed.ref_regex + "': " + str(e))


def main(args):
		# add_help=False,
	parser = CustomParser(
		prog=BINARY_NAME,
		description="Sync Git branches by branch name pattern with corresponding jobs in Jenkins"
	)

	parser.add_argument( '-V','--version', action='version', version='%(prog)s ' + VERSION)

	parser.add_argument(
		'-J', '--host', dest="jenkins_host", action='store', metavar="URL", required=True,
		help="URL to Jenkins in form <protocol>://<host>[:port][<path>]/"
	)
	parser.add_argument(
		'-S', '--key', dest="ssh_key", action='store', metavar="PATH", required=True,
		help="Path to the SSH key used for authentication"
	)
	parser.add_argument(
		'-j', '--jar', dest="jar", action='store', metavar="PATH", required=True,
		help="Path to the Jenkins CLI .jar"
	)
	parser.add_argument(
		'-G', '--git-repo', dest="git_repo_path", action='store', metavar="PATH", required=True,
		help="Path to the Git repository"
	)
	parser.add_argument(
		'-T', '--tpl-job', dest="tpl_job", action='store', metavar="JOBNAME", required=True,
		help="Name of the job used as template"
	)
	parser.add_argument(
		'-n', '--job-name-tpl', dest="jobname_tpl", action='store', metavar="NAME", required=True,
		help="Name template for the jobs being created, should contain \"%%s\" as placeholder for the branch name"
	)
	parser.add_argument(
		'-B', '--branch-placeholder', dest="branch_name_placeholder", action='store', metavar="STRING", required=True,
		help="Placeholder for the branch name in the template job's config"
	)
	parser.add_argument(
		'-R', '--ref-regex', dest="ref_regex", action='store', metavar="REGEX", required=True,
		help="Regular expression matching the branch names to create jobs for"
	)
	parser.add_argument(
		'-a', '--max-commit-age', dest="max_commit_age", action=MaxAgeSwitchAction, type=int, metavar="DAYS", required=False,
		help="Max days the last commit was made on a branch. Defaults to %d" % DEFAULT_MAX_COMMIT_AGE
	)

	parsed = parser.parse_args(args)

	_validate_arguments(parsed)

	sync = GitJenkinsSync(
		parsed.jenkins_host, parsed.jar, parsed.ssh_key,
		parsed.tpl_job, parsed.branch_name_placeholder, parsed.jobname_tpl,
		parsed.git_repo_path, parsed.ref_regex, parsed.max_commit_age
	)

	sync.sync()

if __name__ == "__main__":
	try:
		main(sys.argv[1:])
	except Exception as e:
		print "Error occured: %s" % str(e)

