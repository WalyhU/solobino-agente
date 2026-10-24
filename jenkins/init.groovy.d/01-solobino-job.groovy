// Crea el job del pipeline al arrancar Jenkins (sin asistente de instalación).
import jenkins.model.Jenkins
import hudson.plugins.git.BranchSpec
import hudson.plugins.git.GitSCM
import org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition
import org.jenkinsci.plugins.workflow.job.WorkflowJob

def repo   = System.getenv('SOLOBINO_REPO')   ?: 'https://github.com/WalyhU/solobino-agente.git'
def branch = System.getenv('SOLOBINO_BRANCH') ?: '*/calidad-software'
def name   = 'solobino-calidad'

def jenkins = Jenkins.get()
if (jenkins.getItem(name) == null) {
  def job = jenkins.createProject(WorkflowJob, name)
  job.setDescription('Pipeline de calidad: pruebas, SonarCloud, sandbox Docker, Postman, WebSocket y Selenium.')
  def scm = new GitSCM(GitSCM.createRepoList(repo, null), [new BranchSpec(branch)], null, null, [])
  def definition = new CpsScmFlowDefinition(scm, 'Jenkinsfile')
  definition.setLightweight(true)
  job.setDefinition(definition)
  job.save()
  job.scheduleBuild2(20)
  println "[solobino] Job '${name}' creado y primera ejecución programada."
}
