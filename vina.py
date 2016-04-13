import os
import sys
import glob
import method
import autodock
import shutil

required_programs = ['prepare_ligand4.py', 'prepare_receptor4.py', 'vina', 'babel']

default_settings = {'cpu': '1'}

class Vina(autodock.ADBased):

    def __init__(self, name, site, options):

        super(Vina, self).__init__(name, site, options)

        center = map(str.strip, site[1].split(','))
        boxsize = map(str.strip, site[2].split(','))

        for idx, xyz in enumerate(['x', 'y', 'z']):
            self.options['center_'+xyz] = center[idx]
            self.options['size_'+xyz] = boxsize[idx]

    def write_docking_script(self, filename, file_r, file_l, rescoring=False):
        """write docking script for Vina"""

        # write vina config file
        with open('vina.config', 'w') as cf:
            # write mandatory options
            print >> cf, 'receptor = target.pdbqt'
            print >> cf, 'ligand = lig.pdbqt'
            # write other options
            for key, value in self.options.iteritems():
                print >> cf, key + ' = ' + value
    
        # write vina script
        if not rescoring:
            with open(filename, 'w') as file:
                script ="""#!/bin/bash
set -e
# generate .pdbqt files
prepare_ligand4.py -l %(file_l)s -C -B 'amide_guadinidium' -o lig.pdbqt
prepare_receptor4.py -r %(file_r)s -o target.pdbqt

# run vina
vina --config vina.config > vina.out"""% locals()
                file.write(script)
        else:
            with open(filename, 'w') as file:
                script ="""#!/bin/bash
set -e
# generate .pdbqt files
prepare_ligand4.py -l %(file_l)s -o lig.pdbqt
prepare_receptor4.py -r %(file_r)s -o target.pdbqt

# run vina
vina --score_only --config vina.config > vina.out"""% locals()
                file.write(script)

    def extract_docking_results(self, file_s, input_file_r, extract):
        """Extract output structures in .mol2 formats"""
    
        # exctract structures from .pdbqt file 
        with open('lig_out.pdbqt','r') as pdbqtf:
            with open(file_s, 'w') as sf:
                for line in pdbqtf:
                    if line.startswith('REMARK VINA RESULT:'):
                        score = float(line[19:].split()[0])
                        print >> sf, score

        self.extract_poses(input_file_r, 'vina')

    def write_rescoring_script(self, filename, file_r, file_l):
        self.write_docking_script(filename, file_r, file_l, rescoring=True)
    
    def extract_rescoring_results(self, filename):
        with open(filename, 'a') as ff:
            with open('vina.out', 'r') as outf:
                for line in outf:
                    if line.startswith('Affinity:'):
                        print >> ff, line.split()[1]
    
        os.remove('lig.pdbqt')
        os.remove('target.pdbqt')
        
    def cleanup(self):
        pass
