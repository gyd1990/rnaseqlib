import os, os.path, subprocess, sys, time, getpass
from optparse import OptionParser

def waitUntilDone(jobID, sleep=10):
    """ Waits until a job ID is no longer found in the bjobs output """
    while True:
        output = subprocess.Popen("bjobs %i"%jobID, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        if len(output[0])>0:
            status = output[0].split()[10]
            if status=='DONE':
                break
        time.sleep(sleep)
    time.sleep(sleep)
        
def launchJob(cmd, scriptOptions, verbose=True, test=False,
              queue_type="normal"):
    """ Submits a job on the cluster which will run command 'cmd', with options 'scriptOptions'

    Optionally:
    verbose: output the job script
    test: don't actually submit the job script (usually used in conjunction with verbose)

    Returns a job ID if the job was submitted properly """

    if type(cmd) not in [type(list()), type(tuple())]:
        cmd = [cmd]

    scriptOptions.setdefault("workingdir", os.getcwd())
    scriptOptions.setdefault("ppn", "1")
    scriptOptions.setdefault("jobname", os.path.basename(sys.argv[0]))
    scriptOptions.setdefault("scriptuser", getpass.getuser())
    # remove queue name option
    #scriptOptions.setdefault("queue", queue_type)
    scriptOptions.setdefault("outdir", "")

    scriptOptions["command"] = " ".join(cmd)

    if verbose:
        print "==SUBMITTING TO CLUSTER=="
        print cmd
        print scriptOptions
        
    pid = os.getpid()
    outscriptName = "%s.%i"%(scriptOptions["jobname"], pid)
    
    scriptOptions["outf"] = os.path.abspath(os.path.join(scriptOptions["outdir"], outscriptName+".out"))
    print "Dumping script to: %s" %(scriptOptions["outf"])

    outtext = """#!/bin/sh

    #BSUB -n %(ppn)s 
    #BSUB -R "rusage[mem=2000]"
    #BSUB -o %(outf)s 
    #BSUB -J %(jobname)s

    echo Working directory is %(workingdir)s
    cd %(workingdir)s

    echo "%(command)s"
    %(command)s
    echo "===== %(command)s finished =====" """ % scriptOptions

    if verbose:
        print outscriptName

    call = "bsub "

    if not test:
        try:
            if verbose:
                print "CALL:", call

            qsub = subprocess.Popen(call, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
	    print "Executing: ", scriptOptions["command"]
            qsub.stdin.write(outtext)
            
            output = qsub.communicate()
            if "is submitted to" in output[0]:
                jobID = int(output[0].strip().split()[1][1:-1])
                if verbose:
                    print "Process launched with job ID:", jobID
                return jobID
            else:
                raise Exception("Failed to launch job '%s': %s"%(outscriptName, str(output)))
        except:
            print "failing..."
            raise
    return None

    
if __name__ == "__main__":
    usage = "%prog [options] command\n Automatically creates a job script for the command provided;"+\
        "allows running a script with input arguments, as well as specifying various cluster options"
    
    parser = OptionParser(usage=usage)

    parser.add_option("-d", "--dir", dest="workingdir", help="Working directory (default: current)")
    parser.add_option("-n", "--nodes", dest="nodes", help="Number of nodes or a comma-separated list of nodes to launch to")
    parser.add_option("-p", "--ppn", dest="ppn", help="Requested number of processors (per node) (default: 1)")
    parser.add_option("-j", "--jobname", dest="jobname", help="Job name (default: Mypbm.PID)")
    parser.add_option("-q", "--queue", dest="queue", help="Queue to submit to (default: short)")
    parser.add_option("-o", "--outdir", dest="outdir", help="Directory to save output file to (default:)")
    parser.add_option("-v", "--verbose", dest="verbose", help="Show output script on command line", action="store_true", default=False)
    parser.add_option("-t", "--test", dest="test", help="Write script file but don't run it", default=False,
                      action="store_true")
    parser.add_option("-w", "--wait", dest="wait", help="Wait until job has finished", default=False,
                      action="store_true")
    
    (options, args) = parser.parse_args()

    if len(args) == 0:
        parser.error("Need to define command to run")

    
    scriptOptions = vars(options)

    # delete those options that weren't specified on the command line, as we would like to
    # define the default values for these options in the actual call to launchJob()
    for key in scriptOptions.keys():
        if scriptOptions[key] == None:
            del scriptOptions[key]
            
    jobID = launchJob(args, scriptOptions, options.verbose, options.test)

    if jobID!=None and options.wait:
        waitUntilDone(jobID)


