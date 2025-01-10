def get_electrical_totals
# normal appliance totals
# converted appliance totals
# adjustments solar+storage (turned on or off)
# save total to new column
# results in total load profile
# save solar adjusted load profile to a new column (this is what we'll need to pay for electricity from the utility)

def get_gas_totals
# which appliances are still gas? get their load profiles
# this is what will be subject to gas totals from the utility


def get_load_profiles_for_utility_rates
    get_electrical_totals
    get_gas_totals
    # save as a new CSV -> this should be the final CSV that I can put through electricity rates to get the daily, monthly, and annual electricity bills for gas and electricity from each utility