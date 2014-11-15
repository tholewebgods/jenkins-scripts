import json
import re
import datetime
import time
import os
from dulwich.repo import Repo
from jenkinscli import JenkinsCli
import xml.etree.ElementTree as ET

# This script will create jobs for each remote branch found in the repository
# in the current directory. It will also remove the jobs if the branches are
# no longer exiting.
#
# - The branch name pattern can be configured
# - The template job name can be configured
# - The branch name placeholder in the template job can be configured
# - There are two types of branches: dev and integration branches
# - Integration branches are treated differently - only one branch
#   (general numerically sorted) the highest value will be fitered
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

# match for integration branches
# there might be only one integration branch at the time
INT_BRANCH_MATCHER="^refs/remotes/origin/int/sprint/[0-9]+$"

# ignore commits older than N days commit time
MAX_COMMIT_AGE = 30

def _within_days(timestamp, days):
	"""Return True if the Unix timestamp is within the timerange now - days"""
	return datetime.datetime.fromtimestamp(timestamp) >= (datetime.datetime.now() + datetime.timedelta(days=-days))


def _filter_branches(refs):
	refs = filter(lambda x: _within_days(x[2], MAX_COMMIT_AGE), refs)

	# sort
	refs.sort()
	# higher mumbers first
	refs.reverse()

	_refs = []
	_saw_int_branch = False
	for ref in refs:
		if re.match(INT_BRANCH_MATCHER, ref[0]):
			# ignore int-branches if we saw one already
			if _saw_int_branch:
				continue

			_saw_int_branch = True
		_refs.append(ref)

	return _refs

def _create_job(ref_name):
	j = JenkinsCli(JENKINS_HOST, JENKINS_CLI_JAR, JENKINS_SSH_KEY)

	# load template and replace placeholder in config
	config_template = j.get_job(JOB_TEMPLATE)
	config = config_template.replace(BRANCH_NAME_PLACEHOLDER, ref_name)

	# replace slashes in ref name to  get clean job name and build job name
	filtered_ref_name = ref_name.replace("origin/", "")
	# Python 2.6 does not support flags=..., using (?i)
	filtered_ref_name = re.sub("(?i)[^a-z0-9_-]+", "-", filtered_ref_name)
	job_name = JOB_NAME_TEMPLATE % filtered_ref_name

	print "Creating and enabling job '%s' for branch %s" % (job_name, ref_name)
	j.create_job(job_name, config)
	j.enable_job(job_name)

def _remove_job(ref_name):
	j = JenkinsCli(JENKINS_HOST, JENKINS_CLI_JAR, JENKINS_SSH_KEY)

	# replace slashes in ref name to  get clean job name and build job name
	filtered_ref_name = ref_name.replace("origin/", "")
	# Python 2.6 does not support flags=..., using (?i)
	filtered_ref_name = re.sub("(?i)[^a-z0-9_-]+", "-", filtered_ref_name)
	job_name = JOB_NAME_TEMPLATE % filtered_ref_name

	print "Removing job '%s' for branch '%s'" % (job_name, ref_name)
	j.delete_job(job_name)

def _get_branch_from_config(config):
	root = ET.fromstring(config)

	name_element = root.findall(".//scm/branches/hudson.plugins.git.BranchSpec/name")

	if len(name_element) == 1:
		return name_element[0].text
	else:
		return None

def _get_currently_configured_branches():
	j = JenkinsCli(JENKINS_HOST, JENKINS_CLI_JAR, JENKINS_SSH_KEY)

	jobs = j.get_joblist()

	branches = []

	for job in jobs:
		if re.match("^" + (JOB_NAME_TEMPLATE % ""), job):
                        config = j.get_job(job)
                        branch_name = _get_branch_from_config(config)

			if not re.match("^refs/remotes/", branch_name):
				branch_name = "refs/remotes/" + branch_name

			branches.append(branch_name)

	return branches

def main():
	repo = Repo(REPOSITORY_LOCATION)
	_refs = []

	for ref, sha1 in repo.get_refs().iteritems():
		if re.match(REF_MATCHER, ref):
			obj = repo.get_object(sha1)
			_refs.append([ref, sha1, obj.commit_time])

	refs = _filter_branches(_refs)

	refs = set([x[0] for x in refs])

	print "Found these branches in the repository:\n  %s" % "\n  ".join(refs)


	local_branches = set(_get_currently_configured_branches())

	print "Found these branches configured in Jenkins:\n  %s" % "\n  ".join(local_branches)


	to_remove = local_branches - refs

	if len(to_remove) > 0:
		print "Remove these:\n  %s" % "\n  ".join(to_remove)

		for ref in to_remove:
			_remove_job(ref.replace("refs/remotes/", ""))
	else:
		print "No branch jobs to remove."


	to_create = refs - local_branches

	if len(to_create) > 0:
		print "Create these:\n  %s" % "\n  ".join(to_create)

		for ref in to_create:
			_create_job(ref.replace("refs/remotes/", ""))
	else:
		print "No branch jobs to create."



if __name__ == "__main__":
	try:
		main()
	except Exception as e:
		print "Error occured: %s" % str(e)

