SHELL=bash
jinpDir=dataset/jinp
junoDir=dataset/juno
fragnum:=99
fragseq:=$(shell seq 0 ${fragnum})
xiaoPp=test/xiaopeip

xtest=xtest

xall: $(xtest)/total-hist-x.pdf $(xtest)/total-record-x.csv $(xtest)/submission-hist-x.pdf $(xtest)/submission-record-x.csv
$(xtest)/submission-record-x.csv: $(xtest)/distrecord/submission-distrecord-x.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(xtest)/submission-hist-x.pdf: $(xtest)/distrecord/submission-distrecord-x.h5
	python3 test/draw_dist.py $^ --wthres 20 -o $@
$(xtest)/distrecord/submission-distrecord-x.h5: $(xtest)/ztraining-x.h5 $(xtest)/submission/submission-x.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@ > $@.log 2>&1
$(xtest)/total-record-x.csv: $(xtest)/distrecord/total-distrecord-x.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(xtest)/total-hist-x.pdf: $(xtest)/distrecord/total-distrecord-x.h5
	python3 test/draw_dist.py $^ --wthres 20 -o $@
$(xtest)/distrecord/total-distrecord-x.h5: $(xtest)/ztraining-x.h5 $(xtest)/submission/total-x.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@ > $@.log 2>&1

$(xtest)/submission/submission-x.h5: $(fragseq:%=$(xtest)/unadjusted/unadjusted-x-%.h5)
	mkdir -p $(dir $@)
	python3 test/integrate.py $^ --num ${fragnum} -o $@
$(xtest)/unadjusted/unadjusted-x-%.h5: $(xtest)/ztraining-x.h5 $(xtest)/averspe.h5
	mkdir -p $(dir $@)
	python3 $(mcmc)/mcmcfit.py $< --ref $(word 2,$^) --num ${fragnum} -o $@

# $(xtest)/ztraining-x.h5: $(junoDir)/junoWave2.h5
$(xtest)/ztraining-x.h5: $(jinpDir)/ztraining-1.h5
	mkdir -p $(dir $@)
	python3 test/cut_data.py $^ -o $@ -a -1 -b 1000
# $(xtest)/averspe.h5: $(junoDir)/junoWave2.h5
$(xtest)/averspe.h5: $(jinpDir)/ztraining-0.h5
	python3 test/spe_get.py $^ -o $@ --num 1000 --len 100 -p
