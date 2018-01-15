#!/bin/bash

# compute BLEU

export TEST_TARGETS_REF0=all-notdelex-reference0.lex
export TEST_TARGETS_REF1=all-notdelex-reference1.lex
export TEST_TARGETS_REF2=all-notdelex-reference2.lex

printf " \n Blue score \n "
./multi-bleu.perl ${TEST_TARGETS_REF0} ${TEST_TARGETS_REF1} ${TEST_TARGETS_REF2} < relexicalised_predictions6.txt

cd ..
cd ..
cd meteor-1.5
printf "\n Meteor score \n"
#compute METEOR
java -Xmx2G -jar meteor-1.5.jar ../tripleBaselineSeen/dev_triple6/relexicalised_predictions6.txt ../tripleBaselineSeen/dev_triple6/all-notdelex-refs-meteor.txt -l en -norm -r 3

cd ..
cd tercom-0.7.25
printf "\n TER score \n"
#compute TER
java -jar tercom.7.25.jar -h ../tripleBaselineSeen/dev_triple6/relexicalised_predictions-ter.txt -r ../tripleBaselineSeen/dev_triple6/all-notdelex-refs-ter.txt

