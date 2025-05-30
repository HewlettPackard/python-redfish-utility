// main.c
#include <stdio.h>
#include <dlfcn.h>
#include <string.h>
#include <stdbool.h>

int main() {
    // Define necessary constants
    char* HOSTAPP_ID = "self_register";
    char* HOSTAPP_NAME = "self_register";
    char* SALT = "self_register";

    // Open the shared library
    void* handle = dlopen("/usr/lib64/ilorest_chif.so", RTLD_LAZY);
    if (!handle) {
        fprintf(stderr, "Error loading library: %s\n", dlerror());
        return 1;
    }
    // Clear any existing errors
    dlerror();
    // Get a pointer to the DeleteAppToken function
    int (*delapptoken_function)(char*, char*, char*);
    *(void**)(&delapptoken_function) = dlsym(handle, "DeleteAppToken");
    char* error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating DeleteAppToken: %s\n", error);
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
    // Get a pointer to the VnicExists function
    int (*vnicexists_function)();
    *(void**)(&vnicexists_function) = dlsym(handle, "ReadyToUse");
    error = dlerror();
    if (error) {
        fprintf(stderr, "Error locating VnicExists: %s\n", error);
        dlclose(handle);
        return 1;
    }
    bool (*enabledebug_function)(const char*);
    *(void**)(&enabledebug_function) = dlsym(handle, "enabledebugoutput");
    const char *logdir= "/root/";
    bool b = enabledebug_function(logdir);

    // Check if VNIC exists, 0 means exists
    if (!vnicexists_function()) {
        bool appid_exists = false;
        bool result = appidexists_function(HOSTAPP_ID, &appid_exists);
        if (result) {
            fprintf(stderr, "Error in calling AppIdExistsinTPM function.\n");
            dlclose(handle);
            return 1;
        }
        if (appid_exists) {
            result = delapptoken_function(HOSTAPP_ID, HOSTAPP_NAME, SALT);
            //fprintf(stderr, "Successfully deleted application account for the given user.\n");
        } else {
            //fprintf(stderr, "The application account does not exist.\n");
            dlclose(handle);
            return 2;
        }
    }

    // Close the library
    dlclose(handle);
    return 0;
}
