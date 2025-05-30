// main.c
#include <stdio.h>
#include <string.h>
#include <dlfcn.h>
#include <stdbool.h>


int main() {
    // Open the shared library
    char* HOSTAPP_ID = "self_register";
    char* HOSTAPP_NAME = "self_register";
    char* SALT = "self_register";
    char* error;

    void* handle = dlopen("/usr/lib64/ilorest_chif.so", RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Error loading library: %s\n", dlerror());
        return 1;
    }

    // Clear any existing errors
    dlerror();

    int (*detectilo_function)();
    *(void**)(&detectilo_function) = dlsym(handle, "DetectILO");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating VnicExists: %s\n", error);
        dlclose(handle);
        return 1;
    }

    int (*vnicexists_function)();
    *(void**)(&vnicexists_function) = dlsym(handle, "ReadyToUse");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating VnicExists: %s\n", error);
        dlclose(handle);
        return 1;
    }
    // Get a pointer to the AppIdExistsinTPM function
    int (*appidexists_function)(char*, bool*);
    *(void**)(&appidexists_function) = dlsym(handle, "AppIdExistsinTPM");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating AppIdExistsinTPM: %s\n", error);
        dlclose(handle);
        return 1;
    }

    bool (*enabledebug_function)(const char*);
    *(void**)(&enabledebug_function) = dlsym(handle, "enabledebugoutput");
    const char *logdir= "/root/";
    bool b = enabledebug_function(logdir);

    // Check if VNIC exists, 0 means exists
    int sec_state = -1;
    int ilo_type = -1;
    int res = detectilo_function(HOSTAPP_ID, &ilo_type, &sec_state);
    if (ilo_type == 7) {
        //fprintf(stderr, "iLO7 detected\n");
        return 0;
    } else {
        return 1;
    }
    fprintf(stderr, "iLO Version detected: %d\n", ilo_type);
    // Close the library
    dlclose(handle);
    return 1;
}
