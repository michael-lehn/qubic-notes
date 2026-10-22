# This file contains the PulseFactory class which is used to create the pulses for the QUBIC instrument.
import inspect
import functools
import numpy as np

__all__ = ['PulseShapeFactory']


class Singleton(object):
    """
    The singleton class is used to make sure that there is only one instance of the Chronicle class.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        """
        Create a new instance of the class if it doesn't exist. Otherwise return the existing instance.

        Parameters:
            args (list): The arguments to pass to the class constructor.
            kwargs (dict): The keyword arguments to pass to the class constructor.

        Returns:
            object: The instance of the class.
        """
        if not isinstance(cls._instance, cls):
            cls._instance = object.__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initialize the singleton class.
        """
        if self._initialized:
            return

        self._initialized = True


class PulseShapeFactory(Singleton):
    """
    A factory that generates the pulse shape with given parameters. New pulse shapes can be added by registering them
    to the factory.
    """

    def __init__(self):
        if self._initialized:
            return
        super(PulseShapeFactory, self).__init__()
        self._pulse_shape_functions = {}
        self._load_built_in_pulse_shapes()

    def register_pulse_shape(
            self, pulse_shape_name: str, pulse_shape_function: callable
    ):
        """
        Register a pulse shape to the factory.

        Parameters:
            pulse_shape_name (str): The name of the pulse shape.
            pulse_shape_function (callable): The function that generates the pulse shape.

        Raises:
            RuntimeError: If the pulse shape function is not compatible.

        Note:
            The pulse shape function must take the following parameters:
                1. The pulse shape parameters.
                2. The sampling rate of the pulse shape. In Msps unit.
        """

        # Check if the pulse shape function is callable
        if not callable(pulse_shape_function):
            msg = f"The pulse shape function must be callable. Got {pulse_shape_function}."
            raise RuntimeError(msg)

        # Check if the pulse shape function is compatible with inspect.signature. Make sure it contains
        # a parameter called: sampling_rate

        if not PulseShapeFactory.is_valid_pulse_shape_function(
                pulse_shape_function):
            msg = (
                f"The pulse shape function {pulse_shape_function.__name__} is not compatible."
                f" It must accept 'sampling_rate' parameter.")
            raise RuntimeError(msg)

        # Check if the pulse shape name is already registered
        if pulse_shape_name in self._pulse_shape_functions:
            msg = (
                f"The pulse shape name {pulse_shape_name} has already been registered."
            )

        # Register the pulse shape function
        self._pulse_shape_functions[pulse_shape_name] = pulse_shape_function

    @staticmethod
    def is_valid_pulse_shape_function(func: callable):
        """
        Check if the pulse shape function is valid.

        Parameters:
            func (callable): The pulse shape function to check.

        Returns:
            bool: True if the pulse shape function is valid. False otherwise.
        """

        # Here we check if the function is a callable
        if not callable(func):
            return False

        # Here we check if 'dt' is in the signature of the function,
        # which will always be included when calling the function
        signature = inspect.signature(func)
        return 'dt' in signature.parameters

    def _load_built_in_pulse_shapes(self):
        """
        Load all the built-in pulse shapes.
        """

        # Import all the built-in pulse shapes
        import qubitconfig.envelope_pulse as ep

        # Get all the pulse shapes
        pulse_shapes = inspect.getmembers(
            ep, inspect.isfunction
        )

        # Register all the pulse shapes
        for pulse_shape_name, pulse_shape_function in pulse_shapes:
            # Check they are compatible
            if PulseShapeFactory.is_valid_pulse_shape_function(
                    pulse_shape_function):
                self.register_pulse_shape(
                    pulse_shape_name, pulse_shape_function)

    def calculate_integrated_area(self, pulse_shape_name: str, sampling_rate: float = 1e3, **kwargs):
        """
        Calculate the integrated area of the pulse shape with the given parameters.

        Parameters:
            pulse_shape_name (str): The name of the pulse shape.
            sampling_rate (float): The sampling rate of the pulse shape. In Msps unit.
            kwargs: The parameters of the pulse shape.

        Returns:
            float: The integrated area of the pulse shape.
        """

        pulse_shape_envelope = self.compile_pulse_shape(pulse_shape_name, sampling_rate=sampling_rate, **kwargs)
        time_step = 1 / sampling_rate
        return np.real(pulse_shape_envelope.sum() * time_step)

    def get_pulse_shape_function(self, pulse_shape_name: str):
        """
        Get the pulse shape function with the given name.

        Parameters:
            pulse_shape_name (str): The name of the pulse shape.

        Returns:
            callable: The pulse shape function.
        """

        if pulse_shape_name not in self._pulse_shape_functions:
            msg = f"The pulse shape name {pulse_shape_name} has not been recognized."
            raise RuntimeError(msg)

        @functools.wraps(self._pulse_shape_functions[pulse_shape_name])
        def func(**kwargs):
            # Here we can add more checks and decorations
            return self._pulse_shape_functions[pulse_shape_name](**kwargs)

        return func

    def compile_pulse_shape(self, pulse_shape_name: str, **kwargs):
        """
        Compile the pulse shape with the given parameters.

        Parameters:
            pulse_shape_name (str): The name of the pulse shape.
            kwargs: The parameters of the pulse shape.

        Returns:
            np.ndarray: The compiled pulse shape.
        """

        if pulse_shape_name not in self._pulse_shape_functions:
            msg = f"The pulse shape name {pulse_shape_name} has not been recognized."
            raise RuntimeError(msg)

        return self.get_pulse_shape_function(pulse_shape_name)(**kwargs)

    def get_available_pulse_shapes(self):
        """
        Get the available pulse shapes.

        Returns:
            list: The available pulse shapes.
        """
        return list(self._pulse_shape_functions.keys())
