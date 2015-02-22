
import unittest
import fudge
import mox

import syncgit

class JenkinsTest(unittest.TestCase):

	@fudge.patch("jenkinscli.JenkinsCli")
	def test_create_job(self, JenkinsCli_mock):
		jenkinscli_inst = (JenkinsCli_mock.expects_call()
							.returns_fake())

		(jenkinscli_inst.expects("get_job")
			.with_args("TEMPLATE Build X")
			.returns("<config><branch>BBBBBB</branch></config>"))

		(jenkinscli_inst.expects("create_job")
			.with_args(
				"Build X dev-ACME-123-branch",
				"<config><branch>origin/dev/ACME-123-branch</branch></config>"
			))

		(jenkinscli_inst.expects("enable_job")
			.with_args("Build X dev-ACME-123-branch"))

		jenkins = syncgit.Jenkins("hostname", "/tmp/cli.jar", "/tmp/ssh-key", "TEMPLATE Build X", "BBBBBB", "Build X %s")

		jenkins.create_job("origin/dev/ACME-123-branch")

	@fudge.patch("jenkinscli.JenkinsCli")
	def test_remove_job(self, JenkinsCli_mock):
		jenkinscli_inst = (JenkinsCli_mock.expects_call()
							.returns_fake())

		(jenkinscli_inst.expects("delete_job")
			.with_args("Build X dev-ACME-123-branch"))

		jenkins = syncgit.Jenkins("hostname", "/tmp/cli.jar", "/tmp/ssh-key", "TEMPLATE Build X", "BBBBBB", "Build X %s")

		jenkins.remove_job("origin/dev/ACME-123-branch")

	# Get Jenkins/Git config fragment containing the Git (branches) config
	def _build_br_cfg_fragment(self, name):
		return "".join([
			"<root>",
				"<scm>",
					"<branches>",
						"<hudson.plugins.git.BranchSpec>",
							"<name>",
								name,
							"</name>",
						"</hudson.plugins.git.BranchSpec>",
					"</branches>",
				"</scm>",
			"</root>"
		])

	@fudge.patch("jenkinscli.JenkinsCli")
	def test_get_currently_configured_branches(self, JenkinsCli_mock):
		jenkinscli_inst = (JenkinsCli_mock.expects_call()
							.returns_fake())

		jenkinscli_inst.expects("get_joblist").returns([
			"Build X dev-ACME-123-branch",
			"Build X dev-ACME-987-branch",
			"Build X def-ACME-000-wo-refs-remotes"
		])

		# returns
		def get_job_fake(job_name):
			return {
				"Build X dev-ACME-123-branch": self._build_br_cfg_fragment("refs/heads/dev/ACME-123-branch"),
				"Build X dev-ACME-987-branch": self._build_br_cfg_fragment("refs/heads/dev/ACME-987-branch"),
				"Build X def-ACME-000-wo-refs-remotes": self._build_br_cfg_fragment("refs/heads/dev/ACME-000-wo-refs-remotes")
			}[job_name]

		jenkinscli_inst.provides("get_job").calls(get_job_fake)

		jenkins = syncgit.Jenkins("hostname", "/tmp/cli.jar", "/tmp/ssh-key", "TEMPLATE Build X", "BBBBBB", "Build X %s")

		jenkins.get_currently_configured_branches()


class GitBranchesTest(unittest.TestCase):

	@fudge.patch("dulwich.repo.Repo", "datetime.datetime", "datetime.timedelta")
	def test_get_branches(self, Repo_mock, datetime_datetime_mock, datetime_timedelta_mock):
		repo_inst = Repo_mock.expects_call().returns_fake()

		def pass_through_kwargs(**kwargs):
			return kwargs["days"] * 24 * 60 * 60

		# pass through days delta
		datetime_timedelta_mock.expects_call().calls(pass_through_kwargs)

		# pass through timestamp
		datetime_datetime_mock.provides("fromtimestamp").calls(lambda x: x)

		datetime_datetime_mock.provides("now").returns(1424478767)

		# all branches in repo, the first does not match the pattern
		repo_inst.expects("get_refs").returns({
			"refs/remotes/origin/other/branch": "00000000000",
			"refs/remotes/origin/int/sprint-1": "deadbee0000",
			"refs/remotes/origin/int/sprint-2": "deadbee0001",
			"refs/remotes/origin/dev/ACME-000-branch-too-old": "deadbee9999",
			"refs/remotes/origin/dev/ACME-123-branch": "deadbee1234",
			"refs/remotes/origin/dev/ACME-987-branch": "deadbee9876"
		})

		def get_object_fake(sha1):
			create_commit = lambda t: fudge.Fake('Commit').has_attr(commit_time=t)

			if sha1 == "deadbee9999":
				# too old
				return create_commit(1424478767 - (45 * 24 * 60 * 60))
			else:
				# in time
				return create_commit(1424478767 - (2 * 24 * 60 * 60))

		repo_inst.provides("get_object").calls(get_object_fake)

		gitbranches = syncgit.GitBranches("/path/to/repo", "^refs/remotes/origin/(int/.*|dev/ACME-[0-9]{1,}-.*)$", 42, "^refs/remotes/origin/int/")

		# get set of refs
		branches = gitbranches.get_branches()

		self.assertEquals(len(branches), 3, "There should be the correct number of branches")
		self.assertTrue("refs/remotes/origin/int/sprint-2" in branches, "The branch name should be correct")
		self.assertTrue("refs/remotes/origin/dev/ACME-987-branch" in branches, "The branch name should be correct")
		self.assertTrue("refs/remotes/origin/dev/ACME-123-branch" in branches, "The branch name should be correct")


class GitJenkinsSyncTest(unittest.TestCase):

	def setUp(self):
		self.mox = mox.Mox()

	def tearDown(self):
		self.mox.UnsetStubs()

	def test_sync(self):
		# prepare mock for GitBranches and mock out all methods
		mocked_gitbranches = self.mox.CreateMock(syncgit.GitBranches)
		mocked_gitbranches.get_branches().AndReturn(set([
			"dev/ACME-987-branch",
			"dev/ACME-123-branch"
		]))

		# mock constructor, return instance mock
		self.mox.StubOutWithMock(syncgit, 'GitBranches')
		(syncgit
			.GitBranches("/path/to/repo", "^refs/remotes/origin/(int/.*|dev/ACME-[0-9]{1,}-.*)$", 42, "^refs/remotes/origin/int/")
			.AndReturn(mocked_gitbranches))


		# prepare mock for Jenkins and mock out all methods
		mocked_jenkins = self.mox.CreateMock(syncgit.Jenkins)
		mocked_jenkins.get_currently_configured_branches().AndReturn([
			"dev/ACME-987-branch",
			"dev/ACME-000-branch"
		])
		mocked_jenkins.remove_job(mox.Regex("^dev/ACME-000-branch$")).AndReturn(None)
		mocked_jenkins.create_job(mox.Regex("^dev/ACME-123-branch$")).AndReturn(None)

		# mock constructor, return instance mock
		self.mox.StubOutWithMock(syncgit, 'Jenkins')
		(syncgit
			.Jenkins("hostname", "/tmp/cli.jar", "/tmp/ssh-key", "TEMPLATE Build X", "BBBBBB", "Build X %s")
			.AndReturn(mocked_jenkins))


		self.mox.ReplayAll()

		sync = syncgit.GitJenkinsSync(
			"hostname", "/tmp/cli.jar", "/tmp/ssh-key", "TEMPLATE Build X", "BBBBBB", "Build X %s",
			"/path/to/repo", "^refs/remotes/origin/(int/.*|dev/ACME-[0-9]{1,}-.*)$", 42, "^refs/remotes/origin/int/"
		)

		sync.sync()

		self.mox.VerifyAll()
