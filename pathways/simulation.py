#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Simulation for evaluataion of pathways
# Copyright (C) 2018-2020 Vaclav Petras

# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.

# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

# You should have received a copy of the GNU General Public License along with
# this program; if not, see https://www.gnu.org/licenses/gpl-2.0.html


"""
Simulation for evaluataion of pathways

.. codeauthor:: Vaclav Petras <wenzeslaus gmail com>
"""

from __future__ import print_function, division

import sys
import types
import random
from collections import namedtuple
import numpy as np


from .shipments import (
    F280ShipmentGenerator,
    ParameterShipmentGenerator,
    get_pest_function,
)
from .inspections import (
    is_shipment_diseased,
    inspect_always,
    inspect_first,
    inspect_first_n,
    inspect_one_random,
    inspect_all,
    inspect_shipment_percentage,
    naive_cfrp,
)
from .outputs import (
    Form280,
    PrintReporter,
    MuteReporter,
    SuccessRates,
    pretty_print_shipment_boxes,
    pretty_print_shipment_boxes_only,
    pretty_print_shipment_stems,
)


SimulationResult = namedtuple(
    "SimulationResult",
    ["missing", "num_inspections", "num_boxes_inspected", "num_boxes"],
)


def simulation(
    config, num_shipments, seed, output_f280_file, verbose=False, pretty=None
):
    """Simulate shipments, their infestation, and their inspection

    :param config: Simulation configuration as a dictionary
    :param num_shipments: Number of shipments to generate
    :param f280_file: Filename for output F280 records
    :param verbose: If True, prints messages about each shipment
    """
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements

    # set seeds for all generators used
    if seed is not None:
        random.seed(seed)  # random package
        np.random.seed(seed)  # NumPy and SciPy

    # allow for an empty disposition code specification
    disposition_codes = config.get("disposition_codes", {})
    form280 = Form280(output_f280_file, disposition_codes=disposition_codes)
    if verbose:
        reporter = PrintReporter()
    else:
        reporter = MuteReporter()
    success_rates = SuccessRates(reporter)
    num_inspections = 0
    total_num_boxes_inspected = 0
    total_num_boxes = 0

    if "release_programs" in config:
        if "naive_cfrp" in config["release_programs"]:

            def is_inspection_needed(shipment, date):
                return naive_cfrp(
                    config["release_programs"]["naive_cfrp"], shipment, date
                )

        else:
            raise RuntimeError("Unknown release program: {program}".format(**locals()))
    else:
        is_inspection_needed = inspect_always

    if "input_F280" in config:
        shipment_generator = F280ShipmentGenerator(
            stems_per_box=config["stems_per_box"], filename=config["input_F280"]
        )
    else:
        shipment_generator = ParameterShipmentGenerator(
            parameters=config["shipment"],
            ports=config["ports"],
            stems_per_box=config["stems_per_box"],
            start_date="2020-04-01",
        )

    add_pest = get_pest_function(config)

    inspection_strategy = config["inspection"]["strategy"]
    if inspection_strategy == "percentage":

        def inspect(shipment):
            return inspect_shipment_percentage(
                config=config["inspection"]["percentage"], shipment=shipment
            )

    elif inspection_strategy == "first_n":

        def inspect(shipment):
            return inspect_first_n(
                num_boxes=config["inspection"]["first_n_boxes"], shipment=shipment
            )

    elif inspection_strategy == "first":
        inspect = inspect_first
    elif inspection_strategy == "one_random":
        inspect = inspect_one_random
    elif inspection_strategy == "all":
        inspect = inspect_all
    else:
        raise RuntimeError(
            "Unknown inspection strategy: {inspection_strategy}".format(**locals())
        )

    for unused_i in range(num_shipments):
        shipment = shipment_generator.generate_shipment()
        add_pest(shipment)
        if pretty is None:
            pass
        elif pretty == "boxes":
            pretty_print_shipment_boxes(shipment)
        elif pretty == "boxes_only":
            pretty_print_shipment_boxes_only(shipment)
        elif pretty == "stems":
            pretty_print_shipment_stems(shipment)
        else:
            raise ValueError("Unknown value for pretty: {pretty}".format(**locals()))
        must_inspect, applied_program = is_inspection_needed(
            shipment, shipment["arrival_time"]
        )
        if must_inspect:
            shipment_checked_ok, num_boxes_inspected = inspect(shipment)
            num_inspections += 1
            total_num_boxes_inspected += num_boxes_inspected
            total_num_boxes += shipment["num_boxes"]
        else:
            shipment_checked_ok = True  # assuming or hoping it's ok
        form280.fill(
            shipment["arrival_time"],
            shipment,
            shipment_checked_ok,
            must_inspect,
            applied_program,
        )
        shipment_actually_ok = not is_shipment_diseased(shipment)
        success_rates.record_success_rate(
            shipment_checked_ok, shipment_actually_ok, shipment
        )

    num_diseased = num_shipments - success_rates.ok
    if num_diseased:
        # avoiding float division by zero
        missing = 100 * float(success_rates.false_negative) / (num_diseased)
        if verbose:
            print("Missing {0:.0f}% of shipments with pest.".format(missing))
    else:
        # we didn't miss anything
        missing = 0
    return SimulationResult(
        missing=missing,
        num_inspections=num_inspections,
        num_boxes=total_num_boxes,
        num_boxes_inspected=total_num_boxes_inspected,
    )


def run_simulation(
    config, num_simulations, num_shipments, seed, output_f280_file, verbose, pretty
):
    """Run the simulation function specified number of times

    See :func:`simulation` function for explanation of parameters.

    Returns averages computed from the individual simulation runs.
    """
    try:
        # namedtuple is not applicable since we need modifications
        totals = types.SimpleNamespace(
            missing=0, num_inspections=0, num_boxes=0, num_boxes_inspected=0,
        )
    except AttributeError:
        # Python 2 fallback
        totals = lambda: None  # noqa: E731
        totals.missing = 0
        totals.num_inspections = 0
        totals.num_boxes = 0
        totals.num_boxes_inspected = 0

    for i in range(num_simulations):
        result = simulation(
            config=config,
            num_shipments=num_shipments,
            seed=seed + i if seed else None,
            output_f280_file=output_f280_file,
            verbose=verbose,
            pretty=pretty,
        )
        totals.missing += result.missing
        totals.num_inspections += result.num_inspections
        totals.num_boxes += result.num_boxes
        totals.num_boxes_inspected += result.num_boxes_inspected
    # make these relative (reusing the variables)
    totals.missing /= float(num_simulations)
    totals.num_inspections /= float(num_simulations)
    totals.num_boxes /= float(num_simulations)
    totals.num_boxes_inspected /= float(num_simulations)
    return totals


def load_configuration(filename):
    """Get the configuration from a JSON or YAML file"""
    if filename.endswith(".json"):
        import json  # pylint: disable=import-outside-toplevel

        return json.load(open(filename))
    elif filename.endswith(".yaml") or filename.endswith(".yml"):
        import yaml  # pylint: disable=import-outside-toplevel

        if hasattr(yaml, "full_load"):
            return yaml.full_load(open(filename))
        return yaml.load(open(filename))
    else:
        sys.exit("Unknown file extension (file: {})".format(filename))
