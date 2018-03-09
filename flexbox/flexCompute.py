#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 2017
@author: kostenko

This module contains calculation routines for pre/post processing.
"""
import numpy
from scipy import ndimage
from scipy import signal
import transforms3d

from . import flexUtil
from . import flexData
from . import flexProject

def remove_dark(data):
    '''
    Thresholds the data below the first minimum in the histogram
    '''
    
    import matplotlib.pyplot as plt
    
    print('Removing low intensities...')
    
    # Obtain the first minima on the histogram - assuming this is the border between air and material
    #print('min', data.min())
    #print('max', data.max())
    
    x, y = histogram(data[::2,::2,::2], log = True, plot = False)
    
    # Make sure there are no 0s:
    y = numpy.log(y + 1)    
    y = ndimage.filters.gaussian_filter1d(y, sigma=1)

    # Find air maximum:
    air_index = numpy.argmax(y)
    
    print('Air found at %0.3f' % x[air_index])

    # Find the first shoulder after air peak in the histogram spectrum:
    x = x[air_index:]
    
    yd = abs(numpy.diff(y))
    yd = yd[air_index:]
    y = y[air_index:]
    
    # Minimum derivative = Saddle point or extremum:
    ind = signal.argrelextrema(yd, numpy.less)[0][0]
    min_ind = signal.argrelextrema(y, numpy.less)[0][0]

    plt.figure()
    plt.plot(x, y)
    plt.plot(x[ind], y[ind], '+')
    plt.plot(x[min_ind], y[min_ind], '*')
    plt.show()
    
    # Is it a Saddle point or extremum?
    if abs(ind - min_ind) < 2:    
        threshold = x[ind]         

        print('Minimum found next to the air peak at: %0.3f' % x[ind])        
    else:            
        # Move closer to the air peak since we are looking at some other material             
        threshold = x[ind] - abs(x[ind] - x[0]) / 4 

        print('Saddle point found next to the air peak at: %0.3f' % x[ind])        
                                                                                
    # Zero the intensity below extrema:
    data[data < threshold] = 0

    print('Discarding intensity below %0.3f' % threshold)

    return data
    
def _find_best_flip_(fixed, moving, centre, area = 64):
    """
    Find the orientation of the moving volume with the mallest L2 distance from the fixed volume, 
    given that there is 180 degrees amiguity for each of three axes.
    
    Args:
        fixed(array): 3D volume
        moving(array): 3D volume
        centre(array): corrdinates of the center of rotation
        area(int): radius around the center of rotation to look at
        
    Returns:
        (array): rotation matrix corresponding to the best flip
    
    """
    
    x = int(numpy.round(centre[0]))
    y = int(numpy.round(centre[1]))
    z = int(numpy.round(centre[2]))
    
    # Make sure we are looking at the centers of mass:
    fixed = fixed[x-50:x+50, y-50:y+50, z-50:z+50]
    moving_ = moving[x-50:x+50, y-50:y+50, z-50:z+50]
    
    # Compute L2 norms of different flips:
    L2 = numpy.zeros(4)
    L2[0] = numpy.sum((fixed - moving_)**2)   
    L2[1] = numpy.sum((fixed - numpy.rot90(moving_, 2, axes = (1, 2)))**2)    
    L2[2] = numpy.sum((fixed - numpy.rot90(moving_, 2, axes = (0, 2)))**2)   
    L2[3] = numpy.sum((fixed - numpy.rot90(moving_, 2, axes = (0, 1)))**2)
        
    if numpy.argmin(L2) == 0:       
        R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        
    elif numpy.argmin(L2) == 1:
        
        moving = numpy.rot90(moving, 2, axes = (1, 2))
        R = transforms3d.euler.euler2mat(numpy.pi,0,0)
        
    elif numpy.argmin(L2) == 2:
        
        moving = numpy.rot90(moving, 2, axes = (0, 2))
        R = transforms3d.euler.euler2mat(0, numpy.pi,0)
    
    elif numpy.argmin(L2) == 3:
        
        moving = numpy.rot90(moving, 2, axes = (0, 1))
        R = transforms3d.euler.euler2mat(0, 0, numpy.pi)
    
    return R    

def moments_orientation(data, subsample = 1):
    '''
    Find the center of mass and the intensity axes of the image.
    
    Args:
        data(array): 3D input
        subsample: subsampling factor to to make it faster
        
    Returns:
        T, R: translation vector to the center of mass and rotation matrix to intensity axes 
    
    '''
    # find centroid:
    m000 = moment3(data, [0, 0, 0], subsample = subsample)
    m100 = moment3(data, [1, 0, 0], subsample = subsample)
    m010 = moment3(data, [0, 1, 0], subsample = subsample)
    m001 = moment3(data, [0, 0, 1], subsample = subsample)

    # Somehow this system of coordinates and the system of ndimage.interpolate require negation of j:
    T = [m100 / m000, m010 / m000, m001 / m000]
    
    # find central moments:
    mu200 = moment3(data, [2, 0, 0], T, subsample = subsample)
    mu020 = moment3(data, [0, 2, 0], T, subsample = subsample)
    mu002 = moment3(data, [0, 0, 2], T, subsample = subsample)
    mu110 = moment3(data, [1, 1, 0], T, subsample = subsample)
    mu101 = moment3(data, [1, 0, 1], T, subsample = subsample)
    mu011 = moment3(data, [0, 1, 1], T, subsample = subsample)
    
    # construct covariance matrix and compute rotation matrix:
    M = numpy.array([[mu200, mu110, mu101], [mu110, mu020, mu011], [mu101, mu011, mu002]])

    # Here we dont sort by the intensity axes length... there will be 180 degrees ambiguity    
    vec = numpy.linalg.eig(M)[1]

    #lam = numpy.linalg.eig(M)[0]    
    #R = vec[inds[::-1]]
    R = numpy.array(vec)
    
    T = numpy.array(T) - numpy.array(data.shape) // 2
    
    return T, R
   
def _itk_registration_(fixed, moving):
    """
    Carry out ITK based volume registration (based on Congugate Gradient).
    
    Args:
        fixed (array): fixed 3D array
        moving (array): moving 3D array
        
    Returns:
        moving will be altered in place.
        
        Tfix: translation to the center of the fixed volume
        Tmov: translation to the center of the moving volume
        Ritk: rotation of the moving volume
        
    """
    
    import SimpleITK as sitk
        
    print('Running ITK volume registration.')
    flexUtil.progress_bar(0) 
    
    # Initialize itk images:
    fixed_image =  sitk.GetImageFromArray(fixed)
    moving_image = sitk.GetImageFromArray(moving)
    
    # Regitration:
    registration_method = sitk.ImageRegistrationMethod()

    # Similarity metric settings.
    registration_method.SetMetricAsMattesMutualInformation(numberOfHistogramBins=50)
    registration_method.SetMetricSamplingStrategy(registration_method.REGULAR)
    registration_method.SetMetricSamplingPercentage(0.01)

    registration_method.SetInterpolator(sitk.sitkLinear)

    # Initial centering transform:
    transform = sitk.CenteredTransformInitializer(fixed_image, 
                                                      moving_image, 
                                                      sitk.Euler3DTransform(), 
                                                      sitk.CenteredTransformInitializerFilter.GEOMETRY)
    # Optimizer settings.
    #registration_method.SetOptimizerAsGradientDescent(learningRate=0.5, numberOfIterations=200, convergenceMinimumValue=1e-10, convergenceWindowSize=10)
    registration_method.SetOptimizerAsPowell()
    #registration_method.SetOptimizerAsGradientDescentLineSearch(learningRate=1, numberOfIterations = 100)
    #registration_method.SetOptimizerAsConjugateGradientLineSearch(learningRate=1, numberOfIterations = 100)
    registration_method.SetOptimizerScalesFromPhysicalShift()

    # Setup for the multi-resolution framework.            
    registration_method.SetShrinkFactorsPerLevel(shrinkFactors = [8,1])
    registration_method.SetSmoothingSigmasPerLevel(smoothingSigmas=[8,1])
    registration_method.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()

    # Don't optimize in-place, we would possibly like to run this cell multiple times.
    registration_method.SetInitialTransform(transform, inPlace=False)

    transform = registration_method.Execute(sitk.Cast(fixed_image, sitk.sitkFloat32), 
                                                  sitk.Cast(moving_image, sitk.sitkFloat32))
    
    # This is a bit of woodo to get to the same definition of Euler angles and translation that I use:
    #Titk = -numpy.array(transform.GetParameters()[:2:-1])
    Tmov = numpy.array(transform.GetFixedParameters()[2::-1]) - numpy.array(fixed.shape) // 2
    #Tmov -= numpy.ones(3)
    Tfix = numpy.array(transform.GetParameters()[:2:-1]) + Tmov

    euler = transform.GetParameters()[2::-1]
    Ritk = transforms3d.euler.euler2mat(-euler[0], -euler[1], euler[2])
    
    flexUtil.progress_bar(1) 
    
    print(registration_method.GetOptimizerStopConditionDescription()) 
    
    moving_image = sitk.Resample(moving_image, fixed_image, transform, sitk.sitkLinear, 0.0, moving_image.GetPixelID())
    moving = sitk.GetArrayFromImage(moving_image)    
    
    print('L2 (ITK native transform)', numpy.sqrt(numpy.mean((moving - fixed) ** 2)))
    
    flexUtil.display_slice(fixed - moving, dim = 1, title = 'after ITK')

    return Tmov, Tfix, Ritk
    
def affine(data, matrix, shift):
    """
    Apply 3x3 rotation matrix and shift to a 3D dataset.
    """
   
    # Compute offset:
    T0 = numpy.array(data.shape) // 2
    T1 = numpy.dot(matrix, T0 + shift)

    return ndimage.interpolation.affine_transform(data, matrix, offset = T0-T1, order = 3)
    
def register_volumes(fixed, moving, subsamp = 2, use_CG = True, monochrome = False):
    '''
    Registration of two 3D volumes.
    
    Args:
        fixed (array): reference volume
        moving (array): moving/slave volume
        subsamp (int): subsampling of the moments computation
        use_itk (bool): if True, use congugate descent method after aligning the moments
        monochrome (bool): if True, compares 0/1 images. If false, compares true intensities.
        
    Returns:
        
    '''
    
    if fixed.shape != moving.shape: raise IndexError('Fixed and moving volumes have different dimensions:', fixed.shape, moving.shape)
    
    print('Using image moments to register volumes.')
        
    # Subsample volumes:
    fixed_ = fixed[::subsamp,::subsamp,::subsamp].copy()
    moving_ = moving[::subsamp,::subsamp,::subsamp].copy()
    
    if monochrome:
        fixed_ = fixed_ > 0
        moving_ = moving_ > 0
        
        # Clean up noise close to zero intensity:
        fixed_ = ndimage.morphology.binary_erosion(fixed_).astype(numpy.float32)
        moving_ = ndimage.morphology.binary_erosion(moving_).astype(numpy.float32)

    L2 = numpy.sqrt(numpy.mean(((fixed_ - moving_))**2))
    print('L2 norm before registration: %0.2e' % L2)
    
    flexUtil.progress_bar(0)  
    
    # Positions of the volumes:
    Tfix, Rfix  = moments_orientation(fixed_)
    Tmov, Rmov  = moments_orientation(moving_)
    
    flexUtil.progress_bar(0.1)
    
    # Total rotation and shift:
    Rtot = numpy.dot(Rmov, Rfix.T)
    Ttot = (Tfix) - numpy.dot(Tmov, Rtot)

    # Apply transformation:
    moving_ = affine(moving_, Rtot, Ttot)
    
    # SOlve ambiguity with directions of intensity axes:    
    Rflip = _find_best_flip_(fixed_, moving_, Tfix)
    
    # Update total transform:
    Rtot = numpy.dot(Rtot, Rflip)
    Ttot = (Tfix) - numpy.dot(Tmov, Rtot)
    
    flexUtil.progress_bar(1)
    
    L2 = numpy.sqrt(numpy.mean(((fixed_ - moving_))**2))
    print('L2 norm after moments alignment: %0.2e' % L2)
    
    #print('Found shifts:', Ttot * subsamp)
    #print('Found Euler rotations:', transforms3d.euler.mat2euler(Rtot))  
    
    # Refine registration using ITK optimization:
    if use_CG:
        # Run ITK optimizer at full resolution:    
        #Titk, Ritk = _itk_registration_(fixed_, moving_)
        Tmov_, Tfix_, Ritk = _itk_registration_(fixed_, moving_)
        
        # Update total transform:
        Rtot = numpy.dot(Rtot, Ritk)
        Ttot = (Tfix) - numpy.dot((Tmov), Rtot)    
        
        # Apply transformation:
        moving_ = affine(moving[::subsamp,::subsamp,::subsamp].copy(), Rtot, Ttot)
        
        L2 = numpy.sqrt(numpy.mean(((fixed_ - moving_))**2))
        print('L2 norm after ITK registration: %0.2e' % L2)
        
        
    print('Found shifts:', Ttot * subsamp)
    print('Found Euler rotations:', transforms3d.euler.mat2euler(Rtot))        
    
    return Ttot * subsamp, Rtot 
    
def scale(data, factor):
    '''
    Scales the volume via interpolation.
    '''
    print('Applying scaling.')
    
    flexUtil.progress_bar(0)  
    
    data = ndimage.interpolation.zoom(data, factor)
    
    flexUtil.progress_bar(1)      
    
    return data    
    
def rotate(data, angle, axis = 0):
    '''
    Rotates the volume via interpolation.
    '''
    
    print('Applying rotation.')
    
    flexUtil.progress_bar(0)  
    
    sz = data.shape[axis]
    
    for ii in range(sz):     
        
        sl = flexUtil.anyslice(data, ii, axis)
        
        data[sl] = ndimage.interpolation.rotate(data[sl], angle, reshape=False)
        
        flexUtil.progress_bar((ii+1) / sz)
        
    return data
        
def translate(data, shift, axis = 0):
    """
    Apply a 2D tranlation perpendicular to the axis.
    """
    
    print('Applying translation.')
    
    flexUtil.progress_bar(0)  
    
    sz = data.shape[axis]
    
    for ii in range(sz):     
        
        sl = flexUtil.anyslice(data, ii, axis)
        
        data[sl] = ndimage.interpolation.shift(data[sl], shift, order = 1, reshape=False)
        
        flexUtil.progress_bar((ii+1) / sz)   

    return data
    
def histogram(data, nbin = 256, rng = [], plot = True, log = False):
    """
    Compute histogram of the data.
    """
    
    #print('Calculating histogram...')
    
    if rng == []:
        mi = min(data.min(), 0)
        ma = data.max()
    else:
        mi = rng[0]
        ma = rng[1]

    y, x = numpy.histogram(data, bins = nbin, range = [mi, ma])
    
    # Set bin values to the middle of the bin:
    x = (x[0:-1] + x[1:]) / 2

    if plot:
        flexUtil.plot(x, y, semilogy = log, title = 'Histogram')
    
    return x, y

def intensity_range(data):
    """
    Compute intensity range based on the histogram.
    
    Returns:
        a: position of the highest spike (typically air)
        b: 99.99th percentile
        c: center of mass of the histogram
    """
    # 256 bins should be sufficient for our dynamic range:
    x, y = histogram(data, nbin = 256, plot = False)
    
    # Smooth and find the first and the third maximum:
    y = ndimage.filters.gaussian_filter(numpy.log(y + 0.1), sigma = 1)
    
    # Air:
    a = x[numpy.argmax(y)]
    
    # Most of the other stuff:
    b = numpy.percentile(data, 99.99) 
    
    # Compute the center of mass excluding the high air spike +10% and outlayers:
    y = y[(x > a + (b-a)/10) & (x < b)]    
    x = x[(x > a + (b-a)/10) & (x < b)]
          
    c = numpy.sum(y * x) / numpy.sum(y)  
    
    return [a, b, c] 
    
def centre(data):
        """
        Compute the centre of the square of mass.
        """
        data2 = data.copy()**2
        
        M00 = data2.sum()
                
        return [moment2(data2, 1, 0) / M00, moment2(data2, 1, 1) / M00, moment2(data2, 1, 2) / M00]

def moment3(data, order, center = numpy.zeros(3), subsample = 1):
    '''
    Compute 3D image moments $mu_{ijk}$.
    
    Args:
        data(array): 3D dataset
        order(int): order of the moment
        center(array): coordinates of the center
        subsample: subsampling factor - 1,2,4...
        
    Returns:
        float: image moment
    
    '''
    # Create central indexes:
    shape = data.shape
       
    data_ = data[::subsample, ::subsample, ::subsample].copy()
    
    for dim in range(3):
        if order[dim] > 0:
            
            # Define moment:
            m = numpy.arange(0, shape[dim], dtype = numpy.float32)
            m -= center[dim]
                
            flexUtil.mult_dim(data_, m[::subsample] ** order[dim], dim)    
            
    return numpy.sum(data_) * (subsample**3)
    
def moment2(data, power, dim, centered = True):
    """
    Compute 2D image moments (weighed averages) of the data. 
    
    sum( (x - x0) ** power * data ) 
    
    Args:
        power (float): power of the image moment
        dim (uint): dimension along which to compute the moment
        centered (bool): if centered, center of coordinates is in the middle of array.
        
    """
    
    
    # Create central indexes:
    shape = data.shape

    # Index:        
    x = numpy.arange(0, shape[dim])    
    if centered:
        x -= shape[dim] // 2
    
    x **= power
    
    if dim == 0:
        return numpy.sum(x[:, None, None] * data)
    elif dim == 1:
        return numpy.sum(x[None, :, None] * data)
    else:
        return numpy.sum(x[None, None, :] * data)
        
    def interpolate_holes(self, mask2d, kernel = [3,3,3]):
        '''
        Fill in the holes, for instance, saturated pixels.
        
        Args:
            mask2d: holes are zeros. Mask is the same for all projections.
        '''
        
        flexUtil.progress_bar(0)        
        for ii, block in enumerate(self._parent.data):    
                    
            # Compute the filler:
            tmp = ndimage.filters.gaussian_filter(mask2d, sigma = kernel)        
            tmp[tmp > 0] **= -1

            # Apply filler:                 
            block = block * mask2d[:, None, :]           
            block += ndimage.filters.gaussian_filter(block, sigma = kernel) * (~mask2d[:, None, :])
            
            self._parent.data[ii] = block   

            # Show progress:
            flexUtil.progress_bar((ii+1) / self._parent.data.block_number)
            
        self._parent.meta.history.add_record('process.interpolate_holes(mask2d, kernel)', kernel)

def residual_rings(data, kernel=[3, 1, 3]):
    '''
    Apply correction by computing outlayers .
    '''
    import ndimage
    
    # Compute mean image of intensity variations that are < 5x5 pixels
    print('Our best agents are working on the case of the Residual Rings. This can take years if the kernel size is too big!')

    flexUtil.progress_bar(0)        
    
    tmp = numpy.zeros(data.shape[::2])
    
    for ii in range(data.shape[1]):                 
        
        block = data[:, ii, :]

        # Compute:
        tmp += (block - ndimage.filters.median_filter(block, size = kernel)).sum(1)
        
        flexUtil.progress_bar((ii+1) / data.shape[1])
        
    tmp /= data.shape[1]
    
    print('Subtract residual rings.')
    
    flexUtil.progress_bar(0)        
    
    for ii in range(data.shape[1]):                 
        
        block = data[:, ii, :]
        block -= tmp

        flexUtil.progress_bar((ii+1) / data.shape[1])
        
        data[:, ii, :] = block 
    
    print('Residual ring correcion applied.')
    return data

def subtract_air(data, air_val = None):
    '''
    Subtracts a coeffificient from each projection, that equals to the intensity of air.
    We are assuming that air will produce highest peak on the histogram.
    '''
    print('Air intensity will be derived from 10 pixel wide border.')
    
    # Compute air if needed:
    if air_val is None:  
        
        air_val = -numpy.inf
        
        for ii in range(data.shape[1]): 
            # Take pixels that belong to the 5 pixel-wide margin.
            
            block = data[:, ii, :]

            border = numpy.concatenate((block[:10, :].ravel(), block[-10:, :].ravel(), block[:, -10:].ravel(), block[:, :10].ravel()))
          
            y, x = numpy.histogram(border, 1024, range = [-0.1, 0.1])
            x = (x[0:-1] + x[1:]) / 2
    
            # Subtract maximum argument:    
            air_val = numpy.max([air_val, x[y.argmax()]])
    
    print('Subtracting %f' % air_val)  
    
    flexUtil.progress_bar(0)  
    
    for ii in range(data.shape[1]):  
        
        block = data[:, ii, :]

        block = block - air_val
        block[block < 0] = 0
        
        data[:, ii, :] = block

        flexUtil.progress_bar((ii+1) / data.shape[1])
        
    return data
                    
def _parabolic_min_(values, index, space):    
    '''
    Use parabolic interpolation to find the extremum close to the index value:
    '''
    if (index > 0) & (index < (values.size - 1)):
        # Compute parabolae:
        x = space[index-1:index+2]    
        y = values[index-1:index+2]

        denom = (x[0]-x[1]) * (x[0]-x[2]) * (x[1]-x[2])
        A = (x[2] * (y[1]-y[0]) + x[1] * (y[0]-y[2]) + x[0] * (y[2]-y[1])) / denom
        B = (x[2]*x[2] * (y[0]-y[1]) + x[1]*x[1] * (y[2]-y[0]) + x[0]*x[0] * (y[1]-y[2])) / denom
            
        x0 = -B / 2 / A  
        
    else:
        
        x0 = space[index]

    return x0    
    
def _modifier_l2cost_(projections, geometry, subsample, value, key = 'axs_hrz', display = False):
    '''
    Cost function based on L2 norm of the first derivative of the volume. Computation of the first derivative is done by FDK with pre-initialized reconstruction filter.
    '''
    geometry_ = geometry.copy()
    
    geometry_[key] = value

    vol = flexProject.sample_FDK(projections, geometry_, subsample)

    l2 = 0
    
    for ii in range(vol.shape[0]):
        grad = numpy.gradient(numpy.squeeze(vol[ii, :, :]))
        
        grad = (grad[0] ** 2 + grad[1] ** 2)         
        
        l2 += numpy.sum(grad)
        
    if display:
        flexUtil.display_slice(vol, title = 'Guess = %0.2e, L2 = %0.2e'% (value, l2))    
            
    return -l2    
    
def _optimize_modifier_subsample_(values, projections, geometry, samp = [1, 1], key = 'axs_hrz', display = True):  
    '''
    Optimize a modifier using a particular sampling of the projection data.
    '''  
    maxiter = values.size
    
    # Valuse of the objective function:
    func_values = numpy.zeros(maxiter)    
    
    print('Starting a full search from: %0.3f mm' % values.min(), 'to %0.3f mm'% values.max())
    
    ii = 0
    for val in values:
        func_values[ii] = _modifier_l2cost_(projections, geometry, samp, val, 'axs_hrz', display)

        ii += 1          
    
    min_index = func_values.argmin()    
    
    return _parabolic_min_(func_values, min_index, values)  
        
def optimize_rotation_center(projections, geometry, guess = None, subscale = 1, centre_of_mass = True):
    '''
    Find a center of rotation. If you can, use the center_of_mass option to get the initial guess.
    If that fails - use a subscale larger than the potential deviation from the center. Usually, 8 or 16 works fine!
    '''
    
    # Usually a good initial guess is the center of mass of the projection data:
    if  guess is None:  
        if centre_of_mass:
            
            print('Computing centre of mass...')
            guess = flexData.pixel2mm(centre(projections)[2], geometry)
        
        else:
        
            guess = geometry['axs_hrz']
        
    img_pix = geometry['det_pixel'] / ((geometry['src2obj'] + geometry['det2obj']) / geometry['src2obj'])
    
    print('The initial guess for the rotation axis shift is %0.3f mm' % guess)
    
    # Downscale the data:
    while subscale >= 1:
        
        # Check that subscale is 1 or divisible by 2:
        if (subscale != 1) & (subscale // 2 != subscale / 2): ValueError('Subscale factor should be a power of 2! Aborting...')
        
        print('Subscale factor %1d' % subscale)    

        # We will use constant subscale in the vertical direction but vary the horizontal subscale:
        samp =  [20, subscale]

        # Create a search space of 5 values around the initial guess:
        trial_values = numpy.linspace(guess - img_pix * subscale, guess + img_pix * subscale, 5)
        
        guess = _optimize_modifier_subsample_(trial_values, projections, geometry, samp, key = 'axs_hrz', display = False)
                
        print('Current guess is %0.3f mm' % guess)
        
        subscale = subscale // 2
    
    return guess

def process_flex(path, options = {'bin':1, 'memmap': None}):
    '''
    Read and process the data.
    
    Args:
        path:  path to the flexray data
        options: dictionary of options, such as bin (binning), memmap (use memmap to save RAM)
        
    Return:
        proj: min-log projections
        meta: meta data
        
    '''
    
    bins = options['bin']
    memmap = options['memmap']
    
    # Read:    
    print('Reading...')
    
    dark = flexData.read_raw(path, 'di', sample = [bins, bins])
    flat = flexData.read_raw(path, 'io', sample = [bins, bins])    
    
    proj = flexData.read_raw(path, 'scan_', skip = bins, sample = [bins, bins], memmap = memmap)

    meta = flexData.read_log(path, 'flexray', bins = bins)   
            
    # Prepro:
    print('Processing...')
    proj -= dark
    proj /= (flat.mean(0) - dark)
        
    numpy.log(proj, out = proj)
    proj *= -1
    
    # Fix nans and infs after log:
    proj[~numpy.isfinite(proj)] = 0
    
    proj = flexData.raw2astra(proj)    
    
    return proj, meta

def medipix_quadrant_shift(data):
    '''
    Expand the middle line
    '''
    
    print('Applying medipix pixel shift.')
    
    # this one has to be applied to the whole dataset as it changes its size
    
    flexUtil.progress_bar(0)
    data[:,:, 0:data.shape[2]//2 - 2] = data[:,:, 2:data.shape[2]/2]
    data[:,:, data.shape[2]//2 + 2:] = data[:,:, data.shape[2]//2:-2]

    flexUtil.progress_bar(0.5)

    # Fill in two extra pixels:
    for ii in range(-2,2):
        closest_offset = -3 if (numpy.abs(-3-ii) < numpy.abs(2-ii)) else 2
        data[:,:, data.shape[2]//2 - ii] = data[:,:, data.shape[2]//2 + closest_offset]

    flexUtil.progress_bar(0.7)

    # Then in columns
    data[0:data.shape[0]//2 - 2,:,:] = data[2:data.shape[0]//2,:,:]
    data[data.shape[0]//2 + 2:, :, :] = data[data.shape[0]//2:-2,:,:]

    # Fill in two extra pixels:
    for jj in range(-2,2):
        closest_offset = -3 if (numpy.abs(-3-jj) < numpy.abs(2-jj)) else 2
        data[data.shape[0]//2 - jj,:,:] = data[data.shape[0]//2 + closest_offset,:,:]

    flexUtil.progress_bar(1)

    print('Medipix quadrant shift applied.')    
    
def _find_shift_(data_ref, data_slave, offset, dim = 1):    
    """
    Find a small 2D shift between two 3d images.
    """
    from skimage import feature
    import scipy.ndimage
     
    shifts = []
    
    # Look at a few slices along the dimension dim:
    for ii in numpy.arange(0, data_slave.shape[dim], 100):
        
        # Take a single slice:
        sl = flexUtil.anyslice(data_ref, ii, dim)    
        im_ref = numpy.squeeze(data_ref[sl]).copy()
        sl = flexUtil.anyslice(data_slave, ii, dim)    
        im_slv = numpy.squeeze(data_slave[sl]).copy()
        
        # Make sure that the data we compare is the same size:.        

        im_ref = im_ref[offset[0]:offset[0] + im_slv.shape[0], offset[1]:offset[1] + im_slv.shape[1]]
    
        # Find common area:        
        no_zero = (im_ref * im_slv) != 0

        if no_zero.sum() > 0:
            im_ref *= no_zero
            im_slv *= no_zero
            
            # Crop:
            im_ref = im_ref[numpy.ix_(no_zero.any(1),no_zero.any(0))]    
            im_slv = im_slv[numpy.ix_(no_zero.any(1),no_zero.any(0))]                

            #flexUtil.display_slice(im_ref - im_slv, title = 'im_ref')
                                  
            # Laplace is way better for clipped objects than comparing intensities!
            im_ref = scipy.ndimage.laplace(im_ref)
            im_slv = scipy.ndimage.laplace(im_slv)
        
            # Shift registration with subpixel accuracy (skimage):
            shift, error, diffphase = feature.register_translation(im_ref, im_slv, 10)
            
            shifts.append(shift)
    
    if shifts != []:        
        shift = numpy.mean(shifts, 0)    
        std = numpy.std(shifts, 0)
        
        # Chech that std is at least 2 times less than the shift estimate:
        if all(abs(numpy.array(shift)) > numpy.array(std) * 2):    
            print('Found shift:', shift, 'with STD:', std)
        else:
            print('Found shift:', shift, 'with STD:', std, ". STD too high! Automatic shift correction is not applied." )
            shift = [0, 0]

    else:
        shift = [0, 0]
    
    return shift
    
def append_tile(data, geom, tot_data, tot_geom):
    """
    Append a tile to a larger dataset.
    Args:
        
        data: projection stack
        geom: geometry descritption
        tot_data: output array
        tot_geom: output geometry
        
    """ 
    
    import scipy.ndimage.interpolation as interp
    
    print('Stitching a tile...')               
    
    # Assuming all projections have equal number of angles and same pixel sizes
    total_shape = tot_data.shape[::2]
    det_shape = data.shape[::2]
    
    total_size = flexData.detector_size(total_shape, tot_geom)
    det_size = flexData.detector_size(det_shape, geom)
                    
    # Offset from the left top corner:
    x0 = tot_geom['det_hrz']
    y0 = tot_geom['det_vrt']
    
    x = geom['det_hrz']
    y = geom['det_vrt']
        
    x_offset = ((x - x0) + total_size[1] / 2 - det_size[1] / 2) / geom['det_pixel']
    y_offset = ((y - y0) + total_size[0] / 2 - det_size[0] / 2) / geom['det_pixel']
    
    # Round em up!            
    x_offset = int(numpy.round(x_offset))                   
    y_offset = int(numpy.round(y_offset))                   
                
    # Pad image to get the same size as the total_slice:        
    pad_x = tot_data.shape[2] - data.shape[2]
    pad_y = tot_data.shape[0] - data.shape[0]  
    
    # Collapce both datasets and compute residual shift
    shift = _find_shift_(tot_data, data, [y_offset, x_offset])
    
    x_offset += shift[1]
    y_offset += shift[0]
           
    flexUtil.progress_bar(0) 

    # Apply offsets:
    for ii in range(tot_data.shape[1]):   
        
        # Pad to match sizes:
        proj = numpy.pad(data[:, ii, :], ((0, pad_y), (0, pad_x)), mode = 'constant')  
        
        # Apply shift:
        if (x_offset != 0) | (y_offset != 0):   
            proj = interp.shift(proj, [y_offset, x_offset], order = 1)
                    
        # Add two images in a smart way:
        base = tot_data[:, ii, :]    
        #nozero = (numpy.abs(proj - base) / (numpy.abs(proj) + 1e-5) < 0.2)
        #zero = numpy.logical_not(nozero)
        
        #base[nozero] = numpy.mean((proj, base), 0)[nozero]
        #base[zero] = numpy.max((proj, base), 0)[zero]
        base = numpy.max((proj, base), 0)

        tot_data[:, ii, :] = base
        
        flexUtil.progress_bar((ii+1) / tot_data.shape[1])
        
def apply_edge_ramp(data, width):
    '''
    Apply ramp to the fringe of the tile to reduce artefacts.
    '''
    if numpy.size(width)>1:
        w0 = width[0]
        w1 = width[1]

    else:   
        w0 = width
        w1 = width
    
    # Pad the data:
    data = numpy.pad(data, ((w0, w0), (0,0),(w1, w1)), mode = 'linear_ramp', end_values = 0)
    
    return data
    