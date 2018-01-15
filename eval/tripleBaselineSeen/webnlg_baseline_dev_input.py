import os
import random
import re
import json
import sys
import getopt
from collections import defaultdict
from benchmark_reader import Benchmark

from SPARQLWrapper import SPARQLWrapper, JSON
import nltk
from nltk.tokenize import word_tokenize
import re

ONLINE = False

# pre-compile regexes for the CamelCase converting function
first_cap_re = re.compile('(.)([A-Z][a-z]+)')
all_cap_re = re.compile('([a-z0-9])([A-Z])')

# each ontology class is given a "semantic precision" score (according to http://mappings.dbpedia.org/server/ontology/classes/)
with open('onto_classes_hierarchy.json', encoding="utf8") as f:
    onto_classes_hierarchy = json.load(f)

# dictionary which links an entity with its semantic type / ontology class (ex: Alan_Bean -> ASTRONAUT), used for the delexicalisation
if ONLINE:  # in this case we directly use results from sparql queries on dbpedia (and we build the dictionary)
    delex_dict_dbpd = dict()
else:
    with open('delex_dict_dbpd.json', encoding="utf8") as f:    # in this case we load the dict from a json file
        delex_dict_dbpd = json.load(f)


# put _ between the word
def CamelCase_to_regular(expr):
    s1 = first_cap_re.sub(r'\1 \2', expr)
    return all_cap_re.sub(r'\1 \2', s1).lower()


def select_files(topdir, category='', size=(1, 8)):
    """
    Collect all xml files from a benchmark directory.
    :param topdir: directory with benchmark
    :param category: specify DBPedia category to retrieve texts for a specific category (default: retrieve all)
    :param size: specify size to retrieve texts of specific size (default: retrieve all)
    :return: list of tuples (full path, filename)
    """
# give us the folder for each triple size ,1triple ,2triple etc
    finaldirs = [topdir+'/'+str(item)+'triples' for item in range(size[0], size[1])]
# put all files in each triple size in finalfiles ,i.e in folder 1triple take all files and put them in finalfiles
#list of each triple size files
    finalfileTriple = []
    for item in finaldirs:
        finalfiles = []
        for filename in os.listdir(item):
            finalfiles += [(item, filename)]
        finalfileTriple.append(finalfiles)
   # for fileset in finalfileTriple:
    #    print(fileset)
    #    print('\n')
    # return finalfileTriple
# if category parameter is determined then take in each triple folder just the files contain the specified category
    if category:
        finalfiles = []
        for item in finaldirs:
            finalfiles += [(item, filename) for filename in os.listdir(item) if category in filename]
    return finalfileTriple


def dbpedia_ontology_query(entity):
    sparql = SPARQLWrapper("http://dbpedia.org/sparql")
    sparql.setQuery("""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT ?type
        WHERE { <http://dbpedia.org/resource/""" + entity + """> rdf:type ?type .}
    """)
    sparql.setReturnFormat(JSON)
    
    try:
        results = sparql.query().convert()
        onto_classes = [x["type"]["value"][28:] for x in results["results"]["bindings"] if x["type"]["value"].startswith("http://dbpedia.org/ontology/")]   # we only consider the dbpedia:ontology results
        
        bestScore = 0
        bestType = "NOT_FOUND"
        for type in onto_classes:
            if type in onto_classes_hierarchy:
                if onto_classes_hierarchy[type] > bestScore:
                    bestType = type
                    bestScore = onto_classes_hierarchy[type]
        return bestType.upper() # the ontology class returned is the one with the highest 'semantic precision' score
        
    except Exception:
        return "INVALID_NAME"
# index for put the entity id 
#

def triple_delexicalisation(subj, prop, obj, rplc_dict, index):
#get the semantic type for subject and object
    if subj not in delex_dict_dbpd:
        delex_dict_dbpd[subj] = dbpedia_ontology_query(subj)
        index += 1
    subj_delex = delex_dict_dbpd[subj]
    # if the first letter in object not letter then put its semantic type as its property
    if not(obj[0].isalpha()):   # we avoid to search '25.0' or '"Bread, almonds, garlic, water, olive oil"' on dbpedia
        obj_delex = prop.upper()    # so we just take property to delexicalize the object
        index += 1
    else:# else we search for its semantic type 
        if obj not in delex_dict_dbpd:
            delex_dict_dbpd[obj] = dbpedia_ontology_query(obj)
            index += 1
        obj_delex = delex_dict_dbpd[obj]
  # put in the rplc dictionary each subject and its semantic type and replace _ with space  
    rplc_dict[subj.replace('_', ' ')] = subj_delex
    rplc_dict[obj.replace('_', ' ').replace('"', '')] = obj_delex
    
    return subj_delex, obj_delex, index


def sentence_delexicalisation(sentence, rplc_dict):
# take each target and tokenize it
    sentTokens = word_tokenize(sentence)
# put it in lower case
    sentTokensLow = [t.lower() for t in sentTokens]
    #take all key in rplc_dic and put it in lower case 
    for entity in rplc_dict:
        entTokensLow = [t.lower() for t in word_tokenize(entity)]
        n = len(sentTokens) 
        m = len(entTokensLow)

    # search for matching between subject and object in sentence ,then replace them with thier semantic type
        i=0
        while (i < n - m):
            if entTokensLow == sentTokensLow[i:i+m]:
                sentTokensLow = sentTokensLow[:i]+['X']+sentTokensLow[i+m:]
                sentTokens = sentTokens[:i]+[rplc_dict[entity]]+sentTokens[i+m:]
                i = n - m
            i += 1
    #put generated sentence with space
    sentence_delex = ' '.join(sentTokens)
    return sentence_delex



def create_source_target(b,i, options,folder,dataset, delex=True):
    """
    Write target and source files, and reference files for BLEU.
    :param b: instance of Benchmark class
    :param options: string "delex" or "notdelex" to label files
    :param dataset: dataset part: train, dev, test
    :param delex: boolean; perform delexicalisation or not
    :return: if delex True, return list of replacement dictionaries for each example
    """
#we use word_tokenize to divide words in snetences ,and use sent_tokenize to divide sentences.
    source_out = []
    target_out = []
    rplc_list = []  # store the dict of replacements for each example
    
    index = 0
    print("current number of entry "+str(b.entry_count()))

    for entr in b.entries:
        tripleset = entr.modifiedtripleset
        lexics = entr.lexs
        category = entr.category
        
        triples = ''
        rplc_dict = dict()
        
        for triple in tripleset.triples:
            subj, prop, obj = triple.s, triple.p, triple.o
            if delex:
                subj, obj, index = triple_delexicalisation(subj, prop, obj, rplc_dict, index)
            else:
                subj = ' '.join(word_tokenize(subj.replace('_', ' ')))  # we must be careful with the writing convention, in particulary, punct signs have to be separated from the text
                obj = ' '.join(word_tokenize(obj.replace('_', ' ').replace('"', '')))
            prop = CamelCase_to_regular(prop)
            # add triple after delex as sentence
            triples += subj + ' ' + prop + ' ' + obj + ' '
        
        for lex in lexics:
            if delex:
                sentence = sentence_delexicalisation(lex.lex, rplc_dict)
                rplc_list.append(rplc_dict)
            else:
                sentence = ' '.join(word_tokenize(lex.lex)) # separate punct signs from text
 #source_out contain delex or not delex triple from file ,target_out contain target sentence          
            source_out.append(triples)
            target_out.append(sentence)


    # shuffle two lists in the same way
    random.seed(10)
    
    if delex:
        corpus = list(zip(source_out, target_out, rplc_list))
        random.shuffle(corpus)
        source_out, target_out, rplc_list = zip(*corpus)
    else:
        corpus = list(zip(source_out, target_out))
        random.shuffle(corpus)
        source_out, target_out = zip(*corpus)

# create the files dev-webnlg-all-notdelex.triple | dev-webnlg-all-delex.triple  | dev-webnlg-all-notdelex.lex | dev-webnlg-all-delex.lex
    with open(folder+'/'+dataset + '-triple-'+str(i)+ options + '.triple', 'w+', encoding="utf8") as f:
        f.write('\n'.join(source_out))
    with open(folder+'/'+dataset + '-triple-' +str(i)+ options + '.lex', 'w+', encoding="utf8") as f:
        f.write('\n'.join(target_out))
 
#create separate files with references for multi-bleu.pl for dev set
    scr_refs = defaultdict(list)
# merg source and target in one list and take each source put it as key and its target as value in scr_refs
    if dataset == 'dev' and not delex:
        for src, trg in zip(source_out, target_out):
            scr_refs[src].append(trg)
        # length of the value with max elements
    #sort scr_refs depending on its target length ,and take last one (big one)
        max_refs = sorted(scr_refs.values(), key=len)[-1]
        keys = [key for (key, value) in sorted(scr_refs.items())]
        values = [value for (key, value) in sorted(scr_refs.items())]
        # write the source file not delex
        with open(folder+'/'+options + '-source.triple', 'w+', encoding="utf8") as f:
            f.write('\n'.join(keys))
        # write references files
        for j in range(0, len(max_refs)):
            with open(folder+'/'+options + '-reference' + str(j) + '.lex', 'w+', encoding="utf8") as f:
                out = ''
                for ref in values: 
                    try:
                        out += ref[j] + '\n'
                    except:
                        out += '\n'
                f.write(out)

    return rplc_list

# predfile pred.txt of current triple size
# folder of current triple size 
# n size of current triple
#rplc_list list of dict of replacing 
def relexicalise(predfile,folder,n,rplc_list):
    """
    Take a file from seq2seq output and write a relexicalised version of it.
    :param rplc_list: list of dictionaries of replacements for each example (UPPER:not delex item)
    :return: list of predicted sentences
    """
    relex_predictions = []
    with open(predfile, 'r', encoding="utf8") as f:
        predictions = [line for line in f]
    for i, pred in enumerate(predictions):
        # replace each item in the corresponding example
        rplc_dict = rplc_list[i]
        relex_pred = pred
        for key in rplc_dict:
            relex_pred = relex_pred.replace(rplc_dict[key], key)
        relex_predictions.append(relex_pred)
    # with open('relexicalised_predictions_full.txt', 'w+') as f:
        # f.write(''.join(relex_predictions))

    # create a mapping between not delex triples and relexicalised sents
    with open(folder+'/'+'dev-triple-'+str(n)+'all-notdelex.triple', 'r', encoding="utf8") as f:
        dev_sources = [line.strip() for line in f]
    src_gens = {}
    for src, gen in zip(dev_sources, relex_predictions):
        src_gens[src] = gen  # need only one lex, because they are the same for a given triple

    # write generated sents to a file in the same order as triples are written in the source file
    with open(folder+'/'+'all-notdelex-source.triple', 'r', encoding="utf8") as f:
        triples = [line.strip() for line in f]
    with open(folder+'/'+'relexicalised_predictions'+str(n)+'.txt', 'w+', encoding="utf8") as f:
        for triple in triples:
            f.write(src_gens[triple])

    return relex_predictions


def input_files(path, filepath=None, relex=False):
    """
    Read the corpus, write train and dev files.
    :param path: directory with the WebNLG benchmark
    :param filepath: path to the prediction file with sentences (for relexicalisation)
    :param relex: boolean; do relexicalisation or not
    :return:
    """
    part = 'dev'
    options = ['all-delex', 'all-notdelex']  # generate files with/without delexicalisation  
#files is list of list of tuple for all files in each triple folder
    for option in options:
       files = select_files(path, size=(1, 8))#take general list of files
       # print(files)
       i=0
       for file1 in files:#take each list of tuples
           i+=1
           b = Benchmark()
            #print(file1)
           b.fill_benchmark(file1)#read all xml files in triple1 for example
           print('Its triple size'+str(i))
           #create new folder for each triple size 
           folder='dev_triple'+str(i)
           if not os.path.exists(folder):
               os.makedirs(folder)
           if option == 'all-delex':
              rplc_list = create_source_target(b,i, option,folder, part, delex=True)
              print('Total of {} files processed in {} with {} mode'.format(len(file1), part, option))
           elif option == 'all-notdelex':
              rplc_list = create_source_target(b,i, option,folder,part, delex=False)
              print('Total of {} files processed in {} with {} mode'.format(len(file1), part, option))
           # take each pred file for current triple size 
           if relex and part == 'dev' and option == 'all-delex':
              sizeT=i
              filepath=folder+'/'+'baseline_pred_triple'+str(sizeT)+'.txt'
              print('Path to the file is', filepath)
              relexicalise(filepath,folder,sizeT,rplc_list)
    
    if ONLINE:
        with open('delex_dict_dbpd.json', 'w') as f:
            json.dump(delex_dict_dbpd, f)
    
    print('Files necessary for evaluating are written on disc.')


def main(argv):
    usage = 'usage:\npython3 webnlg_baseline_input.py -i <data-directory>' \
           '\ndata-directory is the directory where you unzipped the archive with data'
    try:
        opts, args = getopt.getopt(argv, 'i:', ['inputdir='])
    except getopt.GetoptError:
        print(usage)
        sys.exit(2)
    input_data = False
    for opt, arg in opts:
        if opt in ('-i', '--inputdir'):
            inputdir = arg
            input_data = True
        else:
            print(usage)
            sys.exit()
    if not input_data:
        print(usage)
        sys.exit(2)
    print('Input directory is ', inputdir)
    input_files(inputdir)
    #input_ONefile(inputdir)


if __name__ == "__main__":
    main(sys.argv[1:])
