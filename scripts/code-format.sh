#!/bin/bash

poetry run black -t py312 -l 80 ananta/*.py tests/*.py

