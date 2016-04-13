import sys
import os
import shutil
import numpy as np
import fileinput
import subprocess
import glob
import time

import stat
import multi
import tools.PDB as pdbt

class ConsensusDocking(object):

    def __init__(self, config, args):

        section = 'DOCKING'
        known_options = ['none', 'clustering', 'rescoring']
        if config.has_option(section, 'consensus'):
            self.type = config.get(section, 'consensus').lower()
            if self.type not in known_options:
                raise ValueError("consensus option should be one of " + ", ".join(known_options))
        else:
            self.type = 'none'

        if self.type == 'clustering':
            default_settings = {'forcefield': 'leaprc.ff14SB', 'cutoff': '2.0'}
            self.clustering = {}
            # load default parameters
            for key, value in default_settings.iteritems():
                self.clustering[key] = value

            # check config file (would possibly overwrite preset parameters)
            if config.has_section(section):
                config_c = dict(config.items(section))
                for key, value in config_c.iteritems():
                    self.clustering[key] = value

        elif self.type == 'rescoring':
            self.rescoring = multi.MultiProgramScoring(config)

        if args.consensus_only:
            self.only = True
        else:
            self.only = False

    def find_consensus(self, instances, input_file_r, site):
    
        if self.type in ['clustering', 'rescoring']:
            tcpu1 = time.time()
            print "Starting consensus..."

            curdir = os.getcwd()
            workdir = 'consensus'
    
            if os.path.isdir(workdir):
                shutil.rmtree(workdir)
            os.mkdir(workdir)
            os.chdir(workdir)
    
            self.prepare_files_for_consensus(instances, site)
            if self.type == 'clustering':
                self.run_tleap(instances)
                self.run_cpptraj()
                self.extract_results()
            elif self.type == 'rescoring':
                self.run_rescoring(input_file_r, site)
            os.chdir(curdir)

            tcpu2 = time.time()
            print "Consensus procedure done. Total time needed: %i s" %(tcpu2-tcpu1)
   
    def prepare_files_for_consensus(self, instances, site):
    
        curdir = os.getcwd()

        posedir = 'poses'
        os.mkdir(posedir)

        # write files containing the number of poses
        # generated by each software
        ff = open(posedir+'/info.dat', 'w')
        ff.write('#program        nposes         site\n')
        
        self.nposes = [1] # number of poses involved for each binding site
        sh = 0 # shift of model

        idx = 0
        for kdx in range(len(site)):
            bs = site['site'+str(kdx+1)] # current binding site
            for name, program, options in instances:
                instdir = '../%s'%name + '.'+bs[0]
                poses_idxs = []
                for filename in glob.glob(instdir+'/lig-*.mol2'):
                    poses_idxs.append(int((filename.split('.')[-2]).split('-')[-1]))
                poses_idxs = sorted(poses_idxs)
                for idx, pose_idx in enumerate(poses_idxs):
                    shutil.copyfile(instdir+'/lig-%s.mol2'%pose_idx, posedir+'/lig-%s.mol2'%(idx+1+sh))
                ff.write('%10s        %s           %s\n'%(program, idx+1, kdx+1))
                sh += idx+1
            self.nposes.append(sh)

    def run_rescoring(self, input_file_r, site):

        for kdx in range(len(site)):
            # iterate over rescoring instances
            for instance, program, options in self.rescoring.instances:
                # get complex filenames 
                files_l = [os.path.abspath('poses/lig-%s.mol2'%idx) for idx in range(self.nposes[kdx], self.nposes[kdx+1]+1)]

                # get docking class
                DockingClass = getattr(sys.modules[program], program.capitalize())

                DockingInstance = DockingClass(instance, site['site'+str(kdx+1)], options)
                DockingInstance.run_rescoring(input_file_r, files_l)

    def run_tleap(self, instances):
    
        curdir = os.getcwd()
    
        # create antechamber dir
        antchmbdir = 'antchmb'
        os.mkdir(antchmbdir)
        os.chdir(antchmbdir)
    
        # get acceptable structure of the ligand
        prgdir = '../../%s'%instances[0][0]
        with open('lig.pdb', 'w') as pdbfout:
            with open(prgdir+'/lig-c.out.pdb', 'r') as pdbfin:
                for line in pdbfin:
                    pdbfout.write(line)
                    if line.startswith('ENDMDL'):
                        break
        subprocess.call('antechamber -i lig.pdb -fi pdb -o lig.mol2 -fo mol2 -at gaff -du y -pf y > antchmb.log', shell=True)
        subprocess.check_call('parmchk -i lig.mol2 -f mol2 -o lig.frcmod', shell=True)
        os.chdir(curdir)

        # purge the rest of files 
        for name, program, options in instances:
            os.remove('../%s'%name+'/lig-c.out.pdb') 
    
        # create antechamber dir
        leapdir = 'LEaP'
        os.mkdir(leapdir)
        os.chdir(leapdir)
    
        # prepare tleap input file
        forcefield = self.clustering['forcefield']
    
        linespdb = ""
        for idx in range(self.nposes):
            if idx == 1:
                linespdb += """p = loadPdb ../poses/rec-lig.%s.pdb
    saveAmberParm p rec-lig.prmtop rec-lig.inpcrd
    savepdb p rec-lig.%s.pdb\n"""%(idx+1,idx+1)
            else:
                linespdb += """p = loadPdb ../poses/rec-lig.%s.pdb
    savepdb p rec-lig.%s.pdb\n"""%(idx+1,idx+1)
    
        linespdb = linespdb[:-1]
    
        with open('leap.in', 'w') as file:
            script ="""source %(forcefield)s
    source leaprc.gaff
    LIG = loadmol2 ../%(antchmbdir)s/lig.mol2
    loadamberparams ../%(antchmbdir)s/lig.frcmod
    %(linespdb)s
    quit"""% locals()
            file.write(script)
    
        # run tleap
        subprocess.check_call('tleap -f leap.in > leap.log', shell=True, executable='/bin/bash')
        os.chdir(curdir)
    
    def run_cpptraj(self):
    
        curdir = os.getcwd()
    
        # create antechamber dir
        clusterdir = 'clstr'
        os.mkdir(clusterdir)
        os.chdir(clusterdir)
    
        lines_trajin = ""
        for idx in range(self.nposes):
            lines_trajin += "trajin ../LEaP/rec-lig.%s.pdb\n"%(idx+1)
    
        # remove last \n
        lines_trajin = lines_trajin[:-1]
        cutoff = self.clustering['cutoff']
    
        # write cpptraj config file to cluster frames
        with open('cpptraj.in', 'w') as file:
            script ="""parm ../LEaP/rec-lig.prmtop
    %(lines_trajin)s
    rms first "@CA,C,N & !:LIG"
    cluster ":LIG & !@/H" nofit mass epsilon %(cutoff)s summary summary.dat info info.dat
    """% locals()
            file.write(script)
    
        subprocess.check_call('cpptraj -i cpptraj.in > cpptraj.log', shell=True)
        os.chdir(curdir)
    
    def extract_results(self):
    
        poses = []
        prgms = []
        idxprgm = -1
        with open('poses/info.dat') as fi:
            for line in fi:
                if not line.startswith('#'):
                    idxprgm += 1
                    prgm = line.split()[0]
                    prgms.append(prgm)
                    n = int(line.split()[1])
                    poses.extend([idxprgm for idx in range(n)])
        nprgms = len(prgms)
        
        clstrs = []
        heterg = []
        ff = open('clstr/info.dat')
        for line in ff:
            # if line does not start with #
            if not line.startswith('#'):
                # indices = numbers of the poses involved in the current cluster
                indices = [i for i, x in enumerate(line.strip()) if x == 'X']
                clstr = []
                for idx in indices:
                    clstr.append([poses[idx], idx])
                clstrs.append(clstr)
                idxs = [x[0] for x in clstr]
                # compute heterogeneity factor for the current cluster
                heterg.append(len(list(set(idxs)))*100./nprgms)
        ff.close()
     
        hetergidxs = np.argsort(-1*np.array(heterg))
        hetmax = heterg[hetergidxs[0]]
        hetmaxs = []
        # in case of equal heterogeneity factors, take the cluster with the most of poses involved
        for idx in hetergidxs:
            if heterg[idx] == hetmax:
                hetmaxs.append(len(clstrs[idx]))
        clstridx = hetergidxs[np.argmax(hetmaxs)]
        file = 'rec-lig.' + str(clstrs[clstridx][0][1]+1) + '.pdb'
        prgmfound =  [prgms[idx] for idx in list(set([x[0] for x in clstrs[clstridx]]))]
        
        with open('info.dat','w') as rf:
            print >> rf, "heterg = %.4f, pose found with %s"%(hetmax,', '.join(prgmfound))
        
        for pose in clstrs[clstridx]:
            file = 'rec-lig.' + str(pose[1]+1) + '.pdb'
            shutil.copyfile('poses/'+file, file)

