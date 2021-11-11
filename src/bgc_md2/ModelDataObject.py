import numpy as np
import xarray as xr
from netCDF4 import Dataset
from sympy import symbols

# from CompartmentalSystems.discrete_model_run import DiscreteModelRun as DMR
from CompartmentalSystems.discrete_model_run_with_gross_fluxes import (
    DiscreteModelRunWithGrossFluxes as DMRWGF,
)

from CompartmentalSystems.pwc_model_run_fd import (
    PWCModelRunFD as PWCMRFD,
    PWCModelRunFDError
)

from bgc_md2.Variable import FixDumbUnits, Variable, StockVariable, FluxVariable


class ModelDataObjectException(Exception):
    def __str__(self):
        return self.args[0]


def readVariable(**keywords):
    ReturnClass = keywords.get("ReturnClass", Variable)
    dataset = keywords["dataset"]
    variable_name = keywords["variable_name"]
    nr_layers = keywords["nr_layers"]
    data_shift = keywords["data_shift"]

    check_units = keywords.get("check_units", True)

    var = dataset[variable_name]
    ## check right output format of data
    try:
        pass
#        if ReturnClass == StockVariable:
#            if check_units and var.cell_methods != "time: instantaneous":
##                pass
#                raise(
#                    ModelDataObjectException(
#                        "Stock data " + variable_name + " is not instantaneous"
#                    )
#                )
#
#        if ReturnClass == FluxVariable:
#            if check_units and var.cell_methods != "time: mean":
##                pass
#                raise(
#                    ModelDataObjectException(
#                        "Flux data " + variable_name + " is not a mean"
#                    )
#                )
    except AttributeError:
#        pass
        if check_units:
            s = "'cell_methods' not specified"
            raise (ModelDataObjectException(s))
        else:
            pass

    ## read variable depending on dimensions
    ndim = var.ndim
    if ndim == 1 + 1:
        # time and depth
        data = var[data_shift:, :nr_layers]
    elif ndim == 1:
        # only time
        data = var[data_shift:]
        # add artificial depth axis
        data = np.expand_dims(data, axis=1)
    else:
        print(var)
        raise (ModelDataObjectException("Data structure not understood"))

    if check_units:
        sdv = ReturnClass(data=data, unit=var.units)
    else:
        sdv = ReturnClass(data=data, unit='1')

    return sdv


def StockDensityVariable2StockVariable(sdv, dz):
    depth_axis = 1
    sv = sdv.data_mult(dz, depth_axis)

    return sv


def getStockVariable_from_Density(**keywords):
    mdo = keywords["mdo"]
    dz = keywords["dz"]
    
    dataset = mdo.dataset
    nstep = mdo.nstep
    stock_unit = mdo.stock_unit
    check_units = mdo.check_units

    sdv = readVariable(ReturnClass=StockVariable, dataset=dataset, **keywords)
    sv = StockDensityVariable2StockVariable(sdv, dz)

    sv_agg = sv.aggregateInTime(nstep)
    if check_units:
        sv_agg.convert(stock_unit)

    return sv_agg


def FluxRateDensityVariable2FluxRateVariable(frdv, dz):
    depth_axis = 1
    frv = frdv.data_mult(dz, depth_axis)

    return frv


def FluxRateVariable2FluxVariable(frv, time):
    time_axis = 0
    dt_data = np.diff(time.data)
    dt = Variable(data=dt_data, unit=time.unit)
    fv = frv.data_mult(dt, time_axis)

    return fv


def getFluxVariable_from_DensityRate(**keywords):
    mdo = keywords["mdo"]
    dz = keywords["dz"]

    dataset = mdo.dataset
    time = mdo.time
    nstep = mdo.nstep
    stock_unit = mdo.stock_unit
    check_units = mdo.check_units

    frdv = readVariable(ReturnClass=FluxVariable, dataset=dataset, **keywords)
    frv = FluxRateDensityVariable2FluxRateVariable(frdv, dz)
    fv = FluxRateVariable2FluxVariable(frv, time)

    fv_agg = fv.aggregateInTime(nstep)
    if check_units:
        fv_agg.convert(stock_unit)

    return fv_agg


def getFluxVariable_from_Rate(**keywords):
    mdo = keywords["mdo"]

    dataset = mdo.dataset
    time = mdo.time
    nstep = mdo.nstep
    stock_unit = mdo.stock_unit
    check_units = mdo.check_units

    frv = readVariable(ReturnClass=FluxVariable, dataset=dataset, **keywords)
    fv = FluxRateVariable2FluxVariable(frv, time)

    fv_agg = fv.aggregateInTime(nstep)
    if check_units:
        fv_agg.convert(stock_unit)
    
    return fv_agg


################################################################################


class ModelDataObject(object):
    def __init__(self, **keywords):
        self.model_structure = keywords["model_structure"]

        # now actually a dictionary containing dask.arrays
        self.dataset = keywords["dataset"]
        stock_unit = keywords["stock_unit"]
        self.stock_unit = FixDumbUnits(stock_unit)
        self.nstep = keywords.get("nstep", 1)
        self.dz_var_names = keywords.get("dz_var_names", dict())

        self.time = keywords["time"]
        self.time_agg = self.time.aggregateInTime(self.nstep)

        self.check_units = keywords.get("check_units", True)

    @classmethod
    def from_dataset(cls, ds, **keywords):
        d = {name: variable for name, variable in ds.variables}
        keywords["dataset"] = d

        return cls(keywords)

    def get_dz(self, pool_name):
        ms = self.model_structure
        dataset = self.dataset

        for item in ms.pool_structure:
            if item["pool_name"] == pool_name:
                dz_var_name = item.get("dz_var", None)

        if dz_var_name is not None:
            dz = self.dz_var_names.get(dz_var_name, None)
            if dz is None:
                dz_var = dataset[dz_var_name]

                dz = Variable(name=dz_var_name, data=dz_var[...], unit=dz_var.units)
        else:
            dz = Variable(name="dz_default", data=np.array([1]), unit="1")

        return dz

    def load_stocks(self, **keywords):
        func = keywords.get("func", getStockVariable_from_Density)
        keywords["data_shift"] = keywords.get("data_shift", 0)
        keywords["check_units"] = self.check_units

        ms = self.model_structure
        time_agg = self.time_agg
        stock_unit = self.stock_unit

        xs_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data), ms.nr_pools)), mask=False
        )
        for item in ms.pool_structure:
            pool_name = item["pool_name"]
            variable_name = item["stock_var"]
            # print(pool_name, variable_name, flush=True)
            nr_layers = ms.get_nr_layers(pool_name)
            dz = self.get_dz(pool_name)

            sv_pool_agg = func(
                mdo=self,
                variable_name=variable_name,
                nr_layers=nr_layers,
                dz=dz,
                **keywords
            )
            for ly in range(nr_layers):
                pool_nr = ms.get_pool_nr(pool_name, ly)
                data = sv_pool_agg.data[:, ly, ...]
                xs_data[..., pool_nr] = data

        xs = StockVariable(name="stocks", data=xs_data, unit=stock_unit)
        return xs

    def _load_external_fluxes(self, **keywords):
        func = keywords["func"]
        flux_structure = keywords["flux_structure"]
        keywords["check_units"] = self.check_units

        ms = self.model_structure
        time_agg = self.time_agg
        stock_unit = self.stock_unit

        fs_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data) - 1, ms.nr_pools)), mask=False
        )

        for pool_name, variable_names in flux_structure.items():
            nr_layers = ms.get_nr_layers(pool_name)
            dz = self.get_dz(pool_name)

            fvs_agg = []
            for variable_name in variable_names:
                # print(pool_name, variable_name, flush=True)
                fv_agg = func(
                    mdo=self,
                    variable_name=variable_name,
                    nr_layers=nr_layers,
                    dz=dz,
                    **keywords
                )
                fvs_agg.append(fv_agg)

            fv_pool_agg = sum(fvs_agg)

            for ly in range(nr_layers):
                pool_nr = ms.get_pool_nr(pool_name, ly)
                data = fv_pool_agg.data[:, ly, ...]
                fs_data[..., pool_nr] = data

        fs = FluxVariable(data=fs_data, unit=self.stock_unit)
        return fs

    def load_external_input_fluxes(self, **keywords):
        return self._load_external_fluxes(
            flux_structure=self.model_structure.external_input_structure, **keywords
        )

    def load_external_output_fluxes(self, **keywords):
        return self._load_external_fluxes(
            flux_structure=self.model_structure.external_output_structure, **keywords
        )

    def load_horizontal_fluxes(self, **keywords):
        func = keywords["func"]
        keywords["check_units"] = self.check_units

        ms = self.model_structure
        time_agg = self.time_agg
        stock_unit = self.stock_unit

        HFs_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data) - 1, ms.nr_pools, ms.nr_pools)),
            mask=False,
        )

        for pools, variable_names in ms.horizontal_structure.items():
            src_pool_name = pools[0]
            tar_pool_name = pools[1]
            # print(src_pool_name, tar_pool_name, flush=True)

            src_nr_layers = ms.get_nr_layers(src_pool_name)
            tar_nr_layers = ms.get_nr_layers(tar_pool_name)
#            assert src_nr_layers == tar_nr_layers
            if src_nr_layers == tar_nr_layers:
                nr_layers = src_nr_layers

                src_dz = self.get_dz(src_pool_name)
                tar_dz = self.get_dz(tar_pool_name)

                assert src_dz.name == tar_dz.name
                dz = src_dz

                fvs_agg = []
                for variable_name in variable_names:
                    fv_agg = func(
                        mdo=self,
                        variable_name=variable_name,
                        nr_layers=nr_layers,
                        dz=dz,
                        **keywords
                    )
                    fvs_agg.append(fv_agg)

                fv_agg = sum(fvs_agg)

                for ly in range(nr_layers):
                    src_pool_nr = ms.get_pool_nr(src_pool_name, ly)
                    tar_pool_nr = ms.get_pool_nr(tar_pool_name, ly)
                    # print(src_pool_name, tar_pool_name, ly, src_pool_nr, tar_pool_nr, flush=True)
                    data = fv_agg.data[:, ly, ...]
                    HFs_data[..., tar_pool_nr, src_pool_nr] = data
            elif src_nr_layers == 1:
                tar_dz = self.get_dz(tar_pool_name)

                fvs_agg = []
                for variable_name in variable_names:
                    fv_agg = func(
                        mdo=self,
                        variable_name=variable_name,
                        nr_layers=tar_nr_layers,
                        dz=tar_dz,
                        **keywords
                    )
                    fvs_agg.append(fv_agg)

                    fv_agg = sum(fvs_agg)

                src_pool_nr = ms.get_pool_nr(src_pool_name, 0)
                for ly in range(tar_nr_layers):
                    tar_pool_nr = ms.get_pool_nr(tar_pool_name, ly)
                    # print(src_pool_name, tar_pool_name, ly, src_pool_nr, tar_pool_nr, flush=True)
                    data = fv_agg.data[:, ly, ...]
                    HFs_data[..., tar_pool_nr, src_pool_nr] = data * 2
            else:
                s = "layer structure for flux between" + \
                    src_pool_name + " and " + tar_pool_name + \
                    " not understood" 
                raise(ModelDataException(s))
                    
        HFs = FluxVariable(
            name="horizontal fluxes", data=HFs_data, unit=self.stock_unit
        )
        return HFs

    def load_vertical_fluxes(self, **keywords):
        func = keywords["func"]
        keywords["check_units"] = self.check_units

        ms = self.model_structure
        time_agg = self.time_agg
        stock_unit = self.stock_unit

        VFs_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data) - 1, ms.nr_pools, ms.nr_pools)),
            mask=False,
        )
        runoffs_up_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data) - 1, ms.nr_pools)), mask=False
        )
        runoffs_down_data = np.ma.masked_array(
            data=np.zeros((len(time_agg.data) - 1, ms.nr_pools)), mask=False
        )

        src_ly_shift = {"to_below": 0, "from_below": 1, "to_above": 0, "from_above": -1}
        tar_ly_shift = {"to_below": 1, "from_below": 0, "to_above": -1, "from_above": 0}

        for pool_name, flux_structure in ms.vertical_structure.items():
            nr_layers = ms.get_nr_layers(pool_name)

            for flux_type in src_ly_shift.keys():
                fvs_agg = []
                variable_names = flux_structure.get(flux_type, None)
                for variable_name in variable_names:
                    # print(pool_name, variable_name, flush=True)
                    fv_agg = func(
                        mdo=self,
                        variable_name=variable_name,
                        nr_layers=nr_layers,
                        **keywords
                    )
                    fvs_agg.append(fv_agg)

                if fvs_agg != []:
                    fv_agg = sum(fvs_agg)
                    for ly in range(nr_layers):
                        pool_nr = ms.get_pool_nr(pool_name, ly)

                        src_ly = ly + src_ly_shift[flux_type]
                        tar_ly = ly + tar_ly_shift[flux_type]
                        if (src_ly in range(nr_layers)) and (
                            tar_ly in range(nr_layers)
                        ):

                            src_pool_nr = ms.get_pool_nr(pool_name, src_ly)
                            tar_pool_nr = ms.get_pool_nr(pool_name, tar_ly)
                            data = fv_agg.data[:, ly, ...]
                            VFs_data[..., tar_pool_nr, src_pool_nr] = data
                        elif src_ly in range(nr_layers) and (tar_ly == -1):
                            src_pool_nr = ms.get_pool_nr(pool_name, src_ly)
                            data = fv_agg.data[:, ly, ...]
                            runoffs_up_data[..., src_pool_nr] = data
                        elif src_ly in range(nr_layers) and (tar_ly == nr_layers):
                            src_pool_nr = ms.get_pool_nr(pool_name, src_ly)
                            data = fv_agg.data[:, ly, ...]
                            runoffs_down_data[..., src_pool_nr] = data

        VFs = FluxVariable(name="vertical_fluxes", data=VFs_data, unit=self.stock_unit)
        runoffs_up = FluxVariable(
            name="runoffs up", data=runoffs_up_data, unit=self.stock_unit
        )
        runoffs_down = FluxVariable(
            name="runoffs down", data=runoffs_down_data, unit=self.stock_unit
        )
        return VFs, runoffs_up, runoffs_down

    def load_xs_Us_Fs_Rs(self):
        xs = self.load_stocks(
            func=getStockVariable_from_Density, data_shift=0)

        Us = self.load_external_input_fluxes(
            func=getFluxVariable_from_DensityRate, data_shift=1
        )

        HFs = self.load_horizontal_fluxes(
            func=getFluxVariable_from_DensityRate, data_shift=1
        )

        ## we ignore runoffs until we might experience existing ones
        ## for a model at some point
        ## then we have to decide what to do with them
        VFs, Runoffs_up, Runoffs_down = self.load_vertical_fluxes(
            func=getFluxVariable_from_Rate, data_shift=1
        )
        # print(np.where(runoffs_up.data !=0))
        # print(np.where(runoffs_down.data !=0))
        # print(runoffs_down.data[runoffs_down.data!=0])

        Fs = HFs + VFs

        Rs = self.load_external_output_fluxes(
            func=getFluxVariable_from_DensityRate, data_shift=1
        )

        return xs, Us, Fs, Rs

    def create_discrete_model_run(self, errors=False):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out
        start_values = xs.data[0, :]

        if (
            xs.data.mask.sum()
            + Fs.data.mask.sum()
            + Us.data.mask.sum()
            + Rs.data.mask.sum()
            == 0
        ):

            # fixme hm 2020-04-21:
            # which reconstruction version is the right choice?
            #            dmr = DMR.reconstruct_from_data(
            #                self.time_agg.data.filled(),
            #                start_values.filled(),
            #                xs.data.filled(),
            #                Fs.data.filled(),
            #                Rs.data.filled(),
            #                Us.data.filled()
            #            )

            #            dmr = DMR.reconstruct_from_fluxes_and_solution(
            dmr = DMRWGF.reconstruct_from_fluxes_and_solution(
                self.time_agg.data.filled(),
                xs.data.filled(),
                Fs.data.filled(),
                Rs.data.filled(),
                Us.data.filled(),
                Fs.data.filled(),
                Rs.data.filled(),
            )
        else:
            dmr = None

        if errors:
            soln_dmr = Variable(data=dmr.solve(), unit=self.stock_unit)
            abs_err = soln_dmr.absolute_error(xs)
            rel_err = soln_dmr.relative_error(xs)

            return dmr, abs_err, rel_err
        else:
            return dmr

    def check_data_consistency(self):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out

        xs_data_save = xs.data
        xs.data = xs.data[:-1, ...]
        
        rhs = (xs + Us + Fs.sum(axis=2) - Fs.sum(axis=1) - Rs)
        rhs.name = 'Data consistency'
        xs.data = xs_data_save[1:, ...]

        abs_err = rhs.absolute_error(xs).max()
        rel_err = rhs.relative_error(xs).max()

        return abs_err, rel_err

    def load_us(self):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out
        times = self.time_agg.data.filled()
        nr_pools = self.model_structure.nr_pools

        data = np.nan * np.ones((len(times), nr_pools))
        try:
            us = PWCMRFD.reconstruct_us(
                times,
                Us.data.filled(),
            )
                
            data[:-1, ...] = us

        except (PWCModelRunFDError, ValueError, OverflowError) as e:
            error = str(e)
            print(error, flush=True)

        return data

    def load_Bs(
        self,
        integration_method='solve_ivp',
        nr_nodes=None,
        check_success=True
    ):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out

        times = self.time_agg.data.filled()
        nr_pools = self.model_structure.nr_pools

        data = np.nan * np.ones((len(times), nr_pools, nr_pools))
#
#        try:
#        Bs = PWCMRFD.reconstruct_Bs(
        Bs, max_abs_err, max_rel_err = PWCMRFD.reconstruct_Bs(
            times,
            xs.data.filled()[0],
            Us.data.filled(),
            Fs.data.filled(),
            Rs.data.filled(),
            xs.data.filled(),
            integration_method,
            nr_nodes,
            check_success
        )
        
        data[:-1, ...] = Bs

        return data, max_abs_err, max_rel_err

    def check_data_consistency(self):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out

        xs_data_save = xs.data
        xs.data = xs.data[:-1, ...]
        
        rhs = (xs + Us + Fs.sum(axis=2) - Fs.sum(axis=1) - Rs)
        rhs.name = 'Data consistency'
        xs.data = xs_data_save[1:, ...]

        abs_err = rhs.absolute_error(xs).max()
        rel_err = rhs.relative_error(xs).max()

        return abs_err, rel_err

    def create_model_run(
        self, 
        integration_method='solve_ivp',
        nr_nodes=None,
        errors=False,
        check_success=True
    ):
        out = self.load_xs_Us_Fs_Rs()
        xs, Us, Fs, Rs = out
        # print(self.time_agg.data)
        # print(xs.data)
        # print(Fs.data)
        # print(Rs.data)
        # print(Us.data)
        # input()

        times = self.time_agg.data.filled()
        # times = np.arange(len(self.time_agg.data))
        if (
            xs.data.mask.sum()
            + Fs.data.mask.sum()
            + Us.data.mask.sum()
            + Rs.data.mask.sum()
            == 0
        ):
            pwc_mr_fd = PWCMRFD.from_gross_fluxes(
                symbols("t"),
                times,
                xs.data.filled()[0],
                Us.data.filled(),
                Fs.data.filled(),
                Rs.data.filled(),
                xs.data.filled(),
                integration_method,
                nr_nodes,
                check_success
            )
        else:
            pwc_mr_fd = None
        

        if errors:
#            print('Computing reconstruction errors')
            err_dict = {}

#            print('  solution error')
            soln = pwc_mr_fd.solve()
            soln_pwc_mr_fd = Variable(
                name="stocks",
                data=soln,
                unit=self.stock_unit
            )
            abs_err = soln_pwc_mr_fd.absolute_error(xs)
            rel_err = soln_pwc_mr_fd.relative_error(xs)
            err_dict["stocks"] = {
                "abs_err": abs_err.max(),
                "rel_err": rel_err.max()
            }

#            print('  input fluxes error')
            Us_pwc_mr_fd = Variable(
                name="acc_gross_external_input_vector",
                data=pwc_mr_fd.acc_gross_external_input_vector(),
                unit=self.stock_unit,
            )
            abs_err = Us_pwc_mr_fd.absolute_error(Us)
            rel_err = Us_pwc_mr_fd.relative_error(Us)
            err_dict["acc_gross_external_inputs"] = {
                "abs_err": abs_err.max(),
                "rel_err": rel_err.max(),
            }

#            print('  output fluxes error')
            Rs_pwc_mr_fd = Variable(
                name="acc_gross_external_output_vector",
                data=pwc_mr_fd.acc_gross_external_output_vector(),
                unit=self.stock_unit,
            )
            abs_err = Rs_pwc_mr_fd.absolute_error(Rs)
            rel_err = Rs_pwc_mr_fd.relative_error(Rs)
            err_dict["acc_gross_external_outputs"] = {
                "abs_err": abs_err.max(),
                "rel_err": rel_err.max(),
            }

#            print('  internal fluxes error')
            Fs_pwc_mr_fd = Variable(
                name="acc_gross_internal_flux_matrix",
                data=pwc_mr_fd.acc_gross_internal_flux_matrix(),
                unit=self.stock_unit,
            )
            abs_err = Fs_pwc_mr_fd.absolute_error(Fs)
            rel_err = Fs_pwc_mr_fd.relative_error(Fs)
            err_dict["acc_gross_internal_fluxes"] = {
                "abs_err": abs_err.max(),
                "rel_err": rel_err.max(),
            }
            abs_err.argmax()
            rel_err.argmax()

#            print('done')
            return pwc_mr_fd, err_dict
        else:
            return pwc_mr_fd, dict()

    def get_stock(self, mr, pool_name, nr_layer=0, name=''):
        ms = self.model_structure
        pool_nr = ms.get_pool_nr(pool_name, nr_layer)
        soln = mr.solve()
        
        if name == '':
            name = ms.get_stock_var(pool_name)
            
        return Variable(
            name=name,
            data=soln[:, pool_nr],
            unit=self.stock_unit
        )

    def get_acc_gross_external_input_flux(self, mr, pool_name, nr_layer=0, name=''):
        ms = self.model_structure
        pool_nr = ms.get_pool_nr(pool_name, nr_layer)
        
        if name == '':
            name = ms.get_external_input_flux_var(pool_name)

        return Variable(
            name=name,
            data=mr.acc_gross_external_input_vector()[:, pool_nr],
            unit=self.stock_unit
        )
    
    def get_acc_gross_external_output_flux(self, mr, pool_name, nr_layer=0, name=''):
        ms = self.model_structure
        pool_nr = ms.get_pool_nr(pool_name, nr_layer)
        
        if name == '':
            name = ms.get_external_output_flux_var(pool_name)

        return Variable(
            name=name,
            data=mr.acc_gross_external_output_vector()[:, pool_nr],
            unit=self.stock_unit
        )
    
    def get_acc_gross_internal_flux(
        self,
        mr,
        pool_name_from,
        pool_name_to,
        nr_layer_from=0,
        nr_layer_to=0,
        name=''
    ):
        ms = self.model_structure
        pool_nr_from = ms.get_pool_nr(
            pool_name_from,
            nr_layer_from
        )
        pool_nr_to = ms.get_pool_nr(
            pool_name_to,
            nr_layer_to
        )
        Fs = mr.acc_gross_internal_flux_matrix()

        if name == '':
            name = ms.get_horizontal_flux_var(pool_name_from, pool_name_to)

        return Variable(
            name=name,
            data=Fs[:, pool_nr_to, pool_nr_from],
            unit=self.stock_unit
        )

#    def get_netcdf(self, mr):
##        ds_attrs = {'time_unit': self.time_agg.unit}
#
##        coords_pool = [d['pool_name'] for d in self.model_structure.pool_structure]
#
#        data_vars = dict()
#        
#        data = mr.start_values
#        start_values = xr.DataArray(
#            data=mr.start_values,
#            dims=['pool'],
##            coords={'pool': coords_pool},
#            attrs={'units': self.stock_unit}
#        )
#        data_vars['start_values'] = start_values
#
#        us = xr.DataArray(
#            data=mr.us,
#            dims=['time', 'pool'],
#            coords={'pool': coords_pool},
#            attrs={'units': self.stock_unit+'/'+self.time_agg.unit}
#        )
#        data_vars['us'] = us
#
#        Bs = xr.DataArray(
#            data=mr.Bs,
#            dims=['time', 'pool_to', 'pool_from'],
#            coords={'pool_to': coords_pool, 'pool_from': coords_pool],
#            attrs={'units': '1/'+self.time_agg.unit}
#        )
#        data_vars['Bs'] = Bs
#
#        ds_mr = xr.Dataset(
##            coords=coords,
#            data_vars=data_vars,
##            attrs=ds_attrs
#        )
##        ds_mr.to_netcdf(file_path)
##        ds_mr.close()
#        return ds_mr
