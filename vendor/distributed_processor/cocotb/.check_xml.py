import xml.etree.ElementTree as et
import sys

if __name__=='__main__':
    results = et.parse(sys.argv[1])
    for child in results.getroot().iter():
        if child.tag == 'failure':
            raise Exception()
