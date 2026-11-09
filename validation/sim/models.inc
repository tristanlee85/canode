* model includes shared by all top-level netlists (paths relative to validation/sim/)
.include models/canode.lib
.include models/vendor/ss34.txt
* TI TPS7B6933-Q1 transient model (unencrypted PSpice; needs ngspice -D ngbehavior=ps)
.include models/vendor/TPS7B6933-Q1_TRANS.lib
