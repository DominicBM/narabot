#! /usr/bin/env python

from __future__ import print_function
import os, subprocess, sys

def make_djvu(infile, outdir):
    base, ext = os.path.splitext(infile)
    outfile = base + ".djvu"
    outpath = os.path.join(outdir, outfile)
#   subprocess.call(["c44", infile, outpath])
    print("Converting {0} => {1}".format(infile, outpath))

def read_manifest(file):
    output = {}
    with open(file, 'r') as f:
        filelist = f.readlines()
        for line in filelist:
            ff = line.split(" ")
            if ff[0] not in output:
                output[ff[0]] = [ff[1].rstrip()]
            else:
                output[ff[0]].append(ff[1].rstrip())
    return output

if __name__ == "__main__":
    path = sys.argv[1]
    print(os.listdir(path))
    for root, dirs, files in os.walk(path):
        # prune files and directories beginning with dot
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        files[:] = [f for f in files if not f.startswith('.')]
        for f in files:
            print(os.path.join(root, f))
    
    filesbyitem = read_manifest(sys.argv[2])
    print(filesbyitem)
    
    for i in filesbyitem:
        for f in filesbyitem[i]:
            make_djvu(f, i)
            
    
    
    #try:
    #    args = getopt.getopt(sys.argv[1:], "")
    #    if len(args) == 1:
    #        print('using glob')
    #        args = glob.glob(args[0])
    #        args.sort()
    #    i = 0
    #    while i < len(args):
    #        make_djvus(args[i])
    #        i = i + 1  
    #except getopt.error, msg:
    #    print(msg)
    #    print("This program has no options")
    #    sys.exit(2)