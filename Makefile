SHELL:=bash
jinpDir:=dataset/jinp
jinpwaveseq:=$(shell seq 0 0)
junoDir:=dataset/juno
junowaveseq:=2 4
fragnum:=99
fragseq:=$(shell seq 0 ${fragnum})
xdcFTp:=test/xdcFT
xiaoPp:=test/xiaopeip
lucy:=test/lucyddm
mcmc:=test/mcmc

.PHONY: all
all: xdcFT xiaopeip lucyddm mcmc junoDataset

mcmc: $(jinpwaveseq:%=$(mcmc)/hist-%.pdf) $(mcmc)/record.csv
$(mcmc)/record.csv: $(jinpwaveseq:%=$(mcmc)/record/record-%.csv)
	cat $^ > $@
$(mcmc)/record/record-%.csv: $(mcmc)/distrecord/distrecord-%.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(mcmc)/hist-%.pdf: $(mcmc)/distrecord/distrecord-%.h5
	python3 test/draw_dist.py $^ --wthres 10 -o $@
$(mcmc)/distrecord/distrecord-%.h5: $(jinpDir)/ztraining-%.h5 $(mcmc)/submission/submission-%.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@ > $@.log 2>&1
define mcmc_split
$(mcmc)/submission/submission-$(1).h5: $(fragseq:%=$(mcmc)/unadjusted/unadjusted-$(1)-%.h5)
	mkdir -p $$(dir $$@)
	python3 test/integrate.py $$^ --num ${fragnum} -o $$@
$(mcmc)/unadjusted/unadjusted-$(1)-%.h5: $(jinpDir)/ztraining-$(1).h5 $(mcmc)/averspe.h5
	mkdir -p $$(dir $$@)
	python3 $(mcmc)/mcmcfit.py $$< --ref $$(word 2,$$^) --num ${fragnum} -o $$@
endef
$(foreach i,$(jinpwaveseq),$(eval $(call mcmc_split,$(i))))
$(mcmc)/averspe.h5: $(jinpDir)/ztraining-0.h5
	python3 test/spe_get.py $^ -o $@ --num 10000 --len 80

lucyddm: $(jinpwaveseq:%=$(lucy)/hist-%.pdf) $(lucy)/record.csv
$(lucy)/record.csv: $(jinpwaveseq:%=$(lucy)/record/record-%.csv)
	cat $^ > $@
$(lucy)/record/record-%.csv: $(lucy)/distrecord/distrecord-%.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(lucy)/hist-%.pdf: $(lucy)/distrecord/distrecord-%.h5
	python3 test/draw_dist.py $^ --wthres 10 -o $@
$(lucy)/distrecord/distrecord-%.h5: $(jinpDir)/ztraining-%.h5 $(lucy)/submission/submission-%.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@
$(lucy)/submission/submission-%.h5 : $(jinpDir)/ztraining-%.h5 $(lucy)/spe.h5
	mkdir -p $(dir $@)
	python3 $(lucy)/lucyDDM.py $< --ref $(word 2,$^) -o $@
$(lucy)/spe.h5: $(jinpDir)/ztraining-0.h5
	python3 test/spe_get.py $^ -o $@ --num 10000 --len 80

xiaopeip: $(jinpwaveseq:%=$(xiaoPp)/hist-%.pdf) $(xiaoPp)/record.csv
$(xiaoPp)/record.csv: $(jinpwaveseq:%=$(xiaoPp)/record/record-%.csv)
	cat $^ > $@
$(xiaoPp)/record/record-%.csv: $(xiaoPp)/distrecord/distrecord-%.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(xiaoPp)/hist-%.pdf: $(xiaoPp)/distrecord/distrecord-%.h5
	python3 test/draw_dist.py $^ --wthres 10 -o $@
$(xiaoPp)/distrecord/distrecord-%.h5: $(jinpDir)/ztraining-%.h5 $(xiaoPp)/submission/submission-%.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@ > $@.log 2>&1
define xpp_split
$(xiaoPp)/submission/submission-$(1).h5: $(xiaoPp)/submission/total-$(1).h5
	mkdir -p $$(dir $$@)
	python3 $(xiaoPp)/adjust.py $$^ -o $$@
$(xiaoPp)/submission/total-$(1).h5: $(fragseq:%=$(xiaoPp)/unadjusted/unadjusted-$(1)-%.h5)
	mkdir -p $$(dir $$@)
	python3 test/integrate.py $$^ --num ${fragnum} -o $$@
$(xiaoPp)/unadjusted/unadjusted-$(1)-%.h5: $(jinpDir)/ztraining-$(1).h5 $(xiaoPp)/averspe.h5
	mkdir -p $$(dir $$@)
	python3 $(xiaoPp)/finalfit.py $$< --ref $$(word 2,$$^) --num ${fragnum} -o $$@
endef
$(foreach i,$(jinpwaveseq),$(eval $(call xpp_split,$(i))))
$(xiaoPp)/averspe.h5: $(jinpDir)/ztraining-0.h5
	python3 test/spe_get.py $^ -o $@ --num 10000 --len 80

xdcFT: $(jinpwaveseq:%=$(xdcFTp)/hist-%.pdf) $(xdcFTp)/record.csv
$(xdcFTp)/record.csv: $(jinpwaveseq:%=$(xdcFTp)/record/record-%.csv)
	cat $^ > $@
$(xdcFTp)/record/record-%.csv: $(xdcFTp)/distrecord/distrecord-%.h5
	mkdir -p $(dir $@)
	python3 test/csv_dist.py $^ -o $@
$(xdcFTp)/hist-%.pdf: $(xdcFTp)/distrecord/distrecord-%.h5
	python3 test/draw_dist.py $^ --wthres 10 -o $@
$(xdcFTp)/distrecord/distrecord-%.h5: $(jinpDir)/ztraining-%.h5 $(xdcFTp)/submission/submission-%.h5
	mkdir -p $(dir $@)
	python3 test/test_dist.py $(word 2,$^) --ref $< -o $@
$(xdcFTp)/submission/submission-%.h5 : $(jinpDir)/ztraining-%.h5 $(xdcFTp)/single_pe.h5
	mkdir -p $(dir $@)
	python3 $(xdcFTp)/FFT_decon.py $< --ref $(word 2,$^) -o $@ -k 0.05 -a 4 -e 4
$(xdcFTp)/single_pe.h5: $(jinpDir)/ztraining-0.h5
	python3 test/spe_get.py $^ -o $@ --num 10000 --len 80

JUNO-Kaon-50.h5:
	wget http://hep.tsinghua.edu.cn/~orv/distfiles/JUNO-Kaon-50.h5

junoDataset: $(junowaveseq:%=$(junoDir)/junoWave%.h5)
$(junoDir)/junoWave2.h5:
	mkdir -p $(dir $@)
	wget https://cloud.tsinghua.edu.cn/f/f6e4cf503be542d3892f/?dl=1 -O $@
$(junoDir)/junoWave4.h5:
	mkdir -p $(dir $@)
	wget https://cloud.tsinghua.edu.cn/f/846ecb6335564714902b/?dl=1 -O $@

.DELETE_ON_ERROR:
.SECONDARY:
