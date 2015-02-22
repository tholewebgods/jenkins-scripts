import json
import re
import datetime
import time
import os
import dulwich.repo
import jenkinscli
import xml.etree.ElementTree as ET

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

# path to the repository. usually "." when this script is run in a
# job that just checks out the branches
REPOSITORY_LOCATION = "."

# Jenkins host URL
JENKINS_HOST = "http://localhost:8080/"
# Path to the private SSH key file
JENKINS_SSH_KEY = "/path/to/id_rsa_local_jenkins_auth"
# Path to the Jenkins CLI .jar
JENKINS_CLI_JAR = "/tmp/jenkins-cli.jar"

# the job name used as a template (this job might/should be disabled)
JOB_TEMPLATE = "TEMPLATE Build project X"
# the job name template to create jobs
# (%s is the placeholder for the branch name)
JOB_NAME_TEMPLATE = "Build Build project X %s"
BRANCH_NAME_PLACEHOLDER="BBBBBBBBBB"

# match these branch names
REF_MATCHER="^refs/remotes/origin/((dev|bugfix)/PROJECT-[0-9]+|int/sprint/[0-9]+)"

# ignore commits older than N days commit time
MAX_COMMIT_AGE = 30

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

def main():
	sync = GitJenkinsSync(
		JENKINS_HOST, JENKINS_CLI_JAR, JENKINS_SSH_KEY,

		JOB_TEMPLATE, BRANCH_NAME_PLACEHOLDER, JOB_NAME_TEMPLATE,

		REPOSITORY_LOCATION, REF_MATCHER, MAX_COMMIT_AGE
	)

	sync.sync()

if __name__ == "__main__":
	try:
		main()
	except Exception as e:
		print "Error occured: %s" % str(e)

