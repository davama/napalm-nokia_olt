#!/bin/bash

rm dist/*

python -m build .

rm -rf napalm_nokia_olt.egg-info
