import numpy as np
from frozendict import frozendict
from sympy import (
    var,
    ImmutableMatrix,
    HadamardProduct,
    diag,
    zeros,
    Symbol,
    symbols,
    solve,
    pi,
    Eq,
    Min,
    Max,
    Matrix,
    Function,
    Piecewise,
    exp,
)
from ComputabilityGraphs.CMTVS import CMTVS
from bgc_md2.helper import bgc_md2_computers
from bgc_md2.resolve.mvars import (
    CompartmentalMatrix,
    InputTuple,
    TimeSymbol,
    StateVariableTuple,
    VegetationCarbonInputScalar,
    VegetationCarbonInputPartitioningTuple,
    VegetationCarbonStateVariableTuple,
    NumericParameterization,
    NumericStartValueDict,
    NumericSimulationTimes,
)
from ..BibInfo import BibInfo


sym_dict = {
    "leaf": "",
    "fine_root": "",
    "wood": "",
    "metabolic_lit": "",
    "structural_lit": "",
    "cwd": "",
    "fast_soil": "",
    "slow_soil": "",
    "passive_soil": "",
    "r_lign_leaf": "",
    "r_lign_fine_root": "",
    "f_lign_fine_root": "",
    "f_lign_leaf": "",
    "f_lign_wood": "",
    "clay": "",
    "silt": "",
    "q_10": "",
    "w_a": "",
    "w_b": "",
    "w_c": "",
    "w_d": "",
    "w_e": "",
    "m_sat": "",
    "xk_opt_litter": "",
    "xk_opt_soil": "",
    "sla": "",
    "b_leaf": "",
    "b_wood": "",
    "b_fine_root": "",
    "glaimax": "",
    "phase_2": "",
    "planttype": "",
    "kwood": "",
    "kmet": "",
    "kstr": "",
    "kcwd": "",
    "kfast": "",
    "kslow": "",
    "kpass": "",
}


for name in sym_dict.keys():
    var(name)


# xk_leaf_cold is temperature scalar for leaf: casa_cnp.F90 Line 785-787
xk_leaf_cold = Function("xk_leaf_cold")
# )
# xk_leaf_dry is the water scalar for leaf: casa_cnp.F90 Line 788-790
xk_leaf_dry = Function("xk_leaf_dry")
btran = Function("btran")
T_air = Function("T_air")
T_soil = Function("T_soil")
bvec_leaf = Function("bvec_leaf")
bvec_fine_root = Function("bvec_fine_root")
bvec_wood = Function("bvec_wood")

kleaf = Function("kleaf")
kfroot = Function("kfroot")
ms = Function("ms")
xk_n_limit = Function("xk_n_limit")
Npp = Function("Npp")
phase = Function("phase")

r_leaf = Function("r_leaf")
r_fine_root = Function("r_fine_root")
r_wood = Function("r_wood")

x = StateVariableTuple(
    (
        leaf,
        fine_root,
        #    wood,
        #    metabolic_lit,
        #    structural_lit,
        #    cwd,
        #    fast_soil,
        #    slow_soil,
        #    passive_soil
    )
)

t = TimeSymbol("t")

# Input = InputTuple(u*ImmutableMatrix(b))
# InputFluxes={
#    leaf      : (ds.NPP * ds.fracCalloc.sel(plant_casa_pools=leaf_ind)),
#    wood      : (ds.NPP * ds.fracCalloc.sel(plant_casa_pools=wood_ind)),
#    fine_root : (ds.NPP * ds.fracCalloc.sel(plant_casa_pools=root_ind))
# }
Input = InputTuple(
    ImmutableMatrix(
        [
            Npp(t) * bvec_leaf(t),
            Npp(t) * bvec_fine_root(t),
            # Npp(t)*bvec_wood(t),
            # 0,
            # 0,
            # 0,
            # 0,
            # 0,
            # 0
        ]
    )
)
# fraction from plant to different litter pools: casa_cnp.F90 Line 969, 970
fac_l = Max(0.001, 0.85 - 0.018 * r_lign_leaf)
fac_r = Max(0.001, 0.85 - 0.018 * r_lign_fine_root)

# formulate as piecewise
xk_leaf_cold_max = Symbol("xk_leaf_cold_max")
T_shed = Symbol("T_shed")


xk_temp = q_10 ** (
    (T_soil(t) - 35 - 273.15) / 10
)  # Temperature scalar for litter and soil: casa_cnp.F90 Line 875

xk_water = ((ms(t) / m_sat - w_b) / (w_a - w_b)) ** w_e * (
    (ms(t) / m_sat - w_c) / (w_a - w_c)
) ** w_d  # Water scalar for litter and soil: casa_cnp.F90 Line 876-877


npool = len(Input)
A = zeros(npool, npool)
for i in range(npool):
    A[i, i] = -1
# A[3, 0] = fac_l                                           # casacnp.F90: Line 969
# A[3, 1] = fac_r                                           # casacnp.F90: Line 970
# A[4, 0] = (1-fac_l)                                       # casacnp.F90: Line 971
# A[4, 1] = (1-fac_r)                                       # casacnp.F90: Line 972
# A[5, 2] = 1                                               # casacnp.F90: Line 973
# A[6, 3] = 0.45                                            # casacnp.F90: Line 1051
# A[6, 4] = 0.45* (1-f_lign_leaf)                           # casacnp.F90: Line 1053
# A[7, 4] = 0.7 * f_lign_leaf                               # casacnp.F90: Line 1055
# A[6, 5] = 0.4 * (1-f_lign_wood)                           # casacnp.F90: Line 1057
# A[7, 5] = 0.7 * f_lign_wood                               # casacnp.F90: Line 1059
# A[7, 6] = (0.85-0.68*(clay+silt))*(0.997-0.032*clay)      # casacnp.F90: Line 1066
# A[8, 6] = (0.85-0.68*(clay+silt))*((1-0.997)+0.032*clay)  # casacnp.F90: Line 1068
# A[8, 7] = 0.45*((1-0.997)+0.009*clay)                     # casacnp.F90: Line 1070
# A[0, 0] = -1
# A[1, 1] = -1
# A[2, 2] = -1
# A[3, 3] = -1
# A[4, 4] = -1
# A[5, 5] = -1
# A[6, 6] = -1
# A[7, 7] = -1
# A[8, 8] = -1
#
k = ImmutableMatrix.diag(
    [
        kleaf(t),
        kfroot(t),
        #   kwood,
        #   kmet,
        #   kstr,
        #   kcwd,
        #   kfast,
        #   kslow,
        #   kpass,
    ],
    unpack=True,
)
epsilon_leaf = (
    1 + xk_leaf_cold(t) / kleaf(t) + xk_leaf_dry(t) / kleaf(t)
)  # Leaf environmental scalar: casa_cnp.F90 Line 975-976
xi = ImmutableMatrix.diag(
    [
        epsilon_leaf,  # casa_cnp.F90: Line 975-976
        1,  # casa_cnp.F90: Line 978
        # 1,                                                                 # casa_cnp.F90: Line 979
        # xk_opt_litter*xk_temp*xk_water*xk_n_limit(t),                      # casa_cnp.F90: Line 880, 1030
        # xk_opt_litter*xk_temp*xk_water*xk_n_limit(t)*exp(-3*f_lign_leaf),  # casa_cnp.F90: Line 880, 1031-1032
        # xk_opt_litter*xk_temp*xk_water*xk_n_limit(t),                      # casa_cnp.F90: Line 880, 1033
        # xk_opt_soil*xk_temp*xk_water*(1-0.75*(silt+clay)),                 # casa_cnp.F90: Line 884, 1035-1036
        # xk_opt_soil*xk_temp*xk_water,                                      # casa_cnp.F90: Line 884, 1037
        # xk_opt_soil*xk_temp*xk_water                                       # casa_cnp.F90: Line 884, 1038
    ],
    unpack=True,
)
B=CompartmentalMatrix(
    HadamardProduct(xi,A*k)
)
print(A.shape, k.shape, xi.shape)
mvs = CMTVS(
    {
        BibInfo(  # Bibliographical Information
            name="cable",
            entryAuthor="Markus Müller",
            # entryAuthorOrcid="",
            # entryCreationDate="22/3/2016",
            # doi="10.5194/bg-10-2255-2013",
            # further_references=BibInfo(doi="10.5194/bg-10-2255-2013"),
            sym_dict=sym_dict,
        ),
        x,  # state vector of the complete system
        t,  # time for the complete system
        Input,  # the overall input
        B,  # the overall compartmental matrix
        #CompartmentalMatrix(xi),
        # VegetationCarbonInputScalar(u),
        # vegetation carbon partitioning.
        # VegetationCarbonInputPartitioningTuple(b),
        # VegetationCarbonStateVariableTuple((C_il, C_is, C_ir)),
    },
    bgc_md2_computers()
)
